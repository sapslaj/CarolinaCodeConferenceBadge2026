"""
code.py -- QR code display for the Carolina Code Conference 2026 badge.
=======================================================================
Puts a scannable QR code on the screen so somebody can point a phone at
your chest and land on a link. SW1/SW2 flip between the codes in the
table below; SW3 mutes the NeoPixels if they are causing glare.

Why the codes are pre-baked
---------------------------
Generating a QR code needs Reed-Solomon encoding, mask selection and
pattern placement -- a few hundred lines, none of which the badge has a
library for and none of which needs to run at runtime, because the
links never change. So the matrices below were generated on a laptop
and pasted in as ASCII art: '#' is a dark module, '.' is a light one.
README.md has the one-line command that produces more of them.

Scanning notes
--------------
- The module size is picked automatically: `fit_scale()` finds the
  largest whole-pixel scale that still leaves a quiet zone, because a
  QR code with no white border around it will not scan. Bigger modules
  scan from further away, which is why the table prefers error
  correction level L -- it keeps the short links at 25x25 modules and
  therefore 4 screen pixels per module instead of 3.
- Nothing on this screen animates and nothing auto-advances. A code
  that changes while somebody is lining up their camera is a code that
  never gets scanned.
"""

# --- backlight off FIRST, before the slow adafruit imports ---------
# Same trick the launcher uses: the panel powers up bright white, so
# claim IO5 and drive it low before spending seconds on imports.
import board
import digitalio
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

import time
import busio
import displayio
import fourwire
import terminalio
import neopixel
import adafruit_st7735r
from adafruit_display_text import label

# `bitmaptools` is a built-in module on the ESP32-S3 CircuitPython
# build. The pure-Python fallback keeps the sample working (a little
# more slowly) on a build without it rather than crashing on import.
try:
    from bitmaptools import fill_region
except ImportError:
    def fill_region(bmp, x1, y1, x2, y2, value):
        for _y in range(y1, y2):
            for _x in range(x1, x2):
                bmp[_x, _y] = value


# ==================================================================
# Screen layout -- the display is 128 wide x 160 tall (portrait).
# The top 128 rows hold the code, the bottom 32 hold the caption.
# ==================================================================
VW = 128
VH = 160
QR_AREA = 128           # the square the code has to fit inside

WHITE = 0               # palette index 0 -- light modules and quiet zone
BLACK = 1               # palette index 1 -- dark modules and the surround


# ==================================================================
# The codes. '#' is a dark module, '.' is light.
#
# Generated with segno (see README.md); do not hand-edit a matrix --
# every module carries error-correction data, so changing one breaks
# the whole code.
# ==================================================================
QR_CODES = (
    {
        "caption": "SCAN ME",
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "matrix": (
            "#######..##.#.##..#######",
            "#.....#.#..#..##..#.....#",
            "#.###.#.#####..#..#.###.#",
            "#.###.#..###.##...#.###.#",
            "#.###.#.#...##.#..#.###.#",
            "#.....#.##..#####.#.....#",
            "#######.#.#.#.#.#.#######",
            "........##.#..##.........",
            "##.#..##..##.##.#.###.##.",
            ".#.#......#####.###.....#",
            "...####.###......#..#..##",
            "####.#.#...#.#...###.....",
            "#.##.##.#...###.####.#.##",
            "...#.#.##.#.#.#...##.##.#",
            "#..#.##.#####.#.#.###.#.#",
            ".##.#...#..#.#..#...#..#.",
            "####..###.##...########..",
            "........#.#.##.##...##..#",
            "#######.###..#.##.#.##.##",
            "#.....#..#..#.###...####.",
            "#.###.#...####..######...",
            "#.###.#.###.#.#....####..",
            "#.###.#......###.#.##.#.#",
            "#.....#.#..###..##...#...",
            "#######.###....##.##...##",
        ),
    },
    {
        "caption": "BADGE HUB",
        "url": "https://badge.sapslaj.cloud",
        "matrix": (
            "#######.####.#....#######",
            "#.....#....##.#...#.....#",
            "#.###.#..#.#.####.#.###.#",
            "#.###.#...####....#.###.#",
            "#.###.#...#####.#.#.###.#",
            "#.....#..#.##.#...#.....#",
            "#######.#.#.#.#.#.#######",
            "........##..###..........",
            "##.##.#..#..#.###.#.....#",
            "#..##...#.#.#.##...#####.",
            ".#....#.##.##.#####..#..#",
            "#.#..#.....#..###.#..####",
            "#####.##.####..#..##....#",
            "##..#..##.##..###...#..#.",
            "##.####.#.#....####.#####",
            "#..#...##.#...##..##.##.#",
            "#.##.##...##.##.#####.##.",
            "........#.#..#..#...#.##.",
            "#######..###....#.#.#...#",
            "#.....#..#.#.##.#...#..#.",
            "#.###.#.##.##.#######....",
            "#.###.#.#.##..#####....##",
            "#.###.#...#####..#..#####",
            "#.....#.####..#...###.###",
            "#######.###.#...#....#..#",
        ),
    },
    {
        "caption": "THE BADGE",
        "url": "https://blog.carolina.codes/p/2026-circuit-board-badge",
        "matrix": (
            "#######...#.####..###..##.#######",
            "#.....#.#.#..######.#.#...#.....#",
            "#.###.#.....##.#..#.#####.#.###.#",
            "#.###.#.###.#.##.#.#..#...#.###.#",
            "#.###.#..#.....#####.###..#.###.#",
            "#.....#.##.##....#...#....#.....#",
            "#######.#.#.#.#.#.#.#.#.#.#######",
            ".........###..#.#...##...........",
            "#####.####.#....##..#...##.#.#.#.",
            "###..#..#.#.####..###..#.##...###",
            "...##.##..#..####.#.#.#.#....#.#.",
            "###..#.#....##.#.....##...##..#..",
            "####..#..##.#.##.#.#....##.###...",
            ".####...##.....##..#####..#....##",
            "##....#.#..##....##.#....##.#..#.",
            ".#..##...#.#..#.#.#.##.#.###..#..",
            ".##..###.###.....#..#..###.##..#.",
            "#..###..#...####..######..#..#.##",
            "#.#...#......###....##...#####.#.",
            "...###.###..##.#..##.#.##...#.#..",
            ".#.##.###.#.#.##.##.....##.##..#.",
            "######.###.....#.#######..##.#.##",
            "#..##.##..###..##.......#.#.##.#.",
            "#...#..#.#.#..###..#.#.#.#...##..",
            "#.#####..#.#...#.#..#..######...#",
            "........###.###.#.#####.#...#.#.#",
            "#######.#.#..######.#.###.#.#..#.",
            "#.....#..#..##..#.#..#..#...###.#",
            "#.###.#.#.#.#.##.#.#....#####..#.",
            "#.###.#.#.#.....#.###..###.###.##",
            "#.###.#.#.###..#..#.###.#.#...#..",
            "#.....#.##.#..###..#.##..##.###..",
            "#######.#.##...#.#....###.#.#..#.",
        ),
    },
)


# A QR matrix is square. Pasting one in with a row dropped or a stray
# character fails deep inside the renderer with an index error, so check
# the shape once at startup and complain in terms of the actual problem.
for _code in QR_CODES:
    _rows = _code["matrix"]
    for _row in _rows:
        if len(_row) != len(_rows):
            raise ValueError("%s: %d rows but one is %d wide -- not square"
                             % (_code["caption"], len(_rows), len(_row)))


# ==================================================================
# Hardware
# ==================================================================
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.25, auto_write=False)


def _btn(pin):
    b = digitalio.DigitalInOut(pin)
    b.switch_to_input(pull=digitalio.Pull.UP)
    return b


sw1 = _btn(board.IO1)
sw2 = _btn(board.IO2)
sw3 = _btn(board.IO43)

# Keep the font chip off the shared SPI bus.
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi,
    command=board.IO6,
    chip_select=board.IO10,
    reset=board.IO7,
    baudrate=8_000_000,
)
display = adafruit_st7735r.ST7735R(
    display_bus,
    width=128,
    height=160,
    rotation=0,
    bgr=True,
    auto_refresh=False,
)


# ==================================================================
# Scene: one 2-colour bitmap for the code, labels underneath.
# ==================================================================
scene = displayio.Group()

qr_pal = displayio.Palette(2)
qr_pal[WHITE] = 0xFFFFFF
qr_pal[BLACK] = 0x000000

canvas = displayio.Bitmap(VW, VH, 2)
scene.append(displayio.TileGrid(canvas, pixel_shader=qr_pal, x=0, y=0))

caption_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF, scale=2)
caption_label.anchor_point = (0.5, 0.5)
caption_label.anchored_position = (VW // 2, 138)
scene.append(caption_label)

hint_label = label.Label(terminalio.FONT, text="SW1/SW2: change", color=0x808080)
hint_label.anchor_point = (0.5, 0.5)
hint_label.anchored_position = (VW // 2, 153)
scene.append(hint_label)

display.root_group = scene


# ==================================================================
# Renderer
# ==================================================================
def fit_scale(modules, area=QR_AREA):
    """Largest whole-pixel module size that still leaves a quiet zone.

    A quiet zone is not decoration -- the spec asks for 4 modules of
    clear margin and most scanners give up well before 0. Prefer a
    bigger module (scans from further away) over a wider margin, but
    never drop the margin below 2 modules.
    """
    for scale in (6, 5, 4, 3, 2):
        for quiet in (4, 3, 2):
            if (modules + 2 * quiet) * scale <= area:
                return scale, quiet
    return 1, 4


def draw_code(idx):
    matrix = QR_CODES[idx]["matrix"]
    n = len(matrix)
    scale, quiet = fit_scale(n)

    block = (n + 2 * quiet) * scale
    ox = (VW - block) // 2                  # centre the white card
    oy = (QR_AREA - block) // 2

    fill_region(canvas, 0, 0, VW, VH, BLACK)
    fill_region(canvas, ox, oy, ox + block, oy + block, WHITE)

    # Dark modules only -- the light ones are already the card colour.
    # Runs of adjacent dark modules in a row are merged into one fill,
    # which roughly halves the number of calls.
    base = quiet * scale
    for row in range(n):
        line = matrix[row]
        y0 = oy + base + row * scale
        col = 0
        while col < n:
            if line[col] != "#":
                col += 1
                continue
            end = col + 1
            while end < n and line[end] == "#":
                end += 1
            fill_region(canvas,
                        ox + base + col * scale, y0,
                        ox + base + end * scale, y0 + scale,
                        BLACK)
            col = end

    caption_label.text = QR_CODES[idx]["caption"]
    display.refresh()
    print("QRCodeDisplay: showing %s (%dx%d modules, %d px/module)"
          % (QR_CODES[idx]["caption"], n, n, scale))


# ==================================================================
# NeoPixels -- a slow breathing sweep to catch an eye from across the
# room. Deliberately dim and deliberately mutable: LEDs this close to
# the panel can throw glare straight into a phone camera.
# ==================================================================
PIXEL_COLOR = (0, 90, 160)
TRAIL = (1.0, 0.35, 0.12, 0.0, 0.0)     # brightness by distance behind the head


def update_leds(t, on):
    if not on:
        for i in range(5):
            pixels[i] = (0, 0, 0)
        pixels.show()
        return
    # One bright pixel walking the strip with a short tail behind it.
    head = int(t * 2.0) % 5
    for i in range(5):
        level = TRAIL[(head - i) % 5]
        pixels[i] = (int(PIXEL_COLOR[0] * level),
                     int(PIXEL_COLOR[1] * level),
                     int(PIXEL_COLOR[2] * level))
    pixels.show()


# ==================================================================
# Main loop -- poll the switches, and otherwise leave the screen alone.
# ==================================================================
idx = 0
leds_on = True
draw_code(idx)
bl.value = True

sw1_prev = sw2_prev = sw3_prev = True
led_at = 0.0

while True:
    now = time.monotonic()
    v1, v2, v3 = sw1.value, sw2.value, sw3.value

    if (not v1) and sw1_prev:
        idx = (idx - 1) % len(QR_CODES)
        draw_code(idx)
    if (not v2) and sw2_prev:
        idx = (idx + 1) % len(QR_CODES)
        draw_code(idx)
    if (not v3) and sw3_prev:
        leds_on = not leds_on
        update_leds(now, leds_on)
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    if leds_on and now - led_at >= 0.08:
        led_at = now
        update_leds(now, True)

    time.sleep(0.02)
