"""
code.py -- Conway's Game of Life for the Carolina Code Conference 2026 badge.
============================================================================
A 64x72 torus running Conway's Life, seeded from a menu of the classic
patterns or from random soup. It watches itself for stalemates and
reseeds when nothing is happening any more, so the badge can sit on a
table running forever.

Controls
--------
  SW1  -- next seed (cycles the patterns below, then random soup)
  SW2  -- pause / resume  (while paused, SW1 single-steps one generation)
  SW3  -- speed: fast / normal / slow

The rules, for completeness: a live cell with 2 or 3 live neighbours
survives, a dead cell with exactly 3 is born, everything else dies.

How this is fast enough
-----------------------
The obvious implementation visits every cell and counts its eight
neighbours. On a 64x72 grid that is 4608 cells and ~37000 neighbour
reads per generation, which in CircuitPython is a slideshow.

So this does not do that. Each *row* is stored as one Python integer,
one bit per cell, and a whole row of neighbour counts is computed with
about twenty integer operations -- no per-cell loop at all. Python
integers are arbitrary width and the operations happen in C, so a
64-wide row costs the same as an 8-wide one.

The trick is a carry-save adder. You cannot add two bitmaps directly,
but you can add them the way hardware does: `a ^ b` is the sum bit and
`a & b` is the carry, so a stack of XOR/AND pairs adds several bitmaps
at once and leaves the count in binary *across* several words. Three
words hold a 0..9 neighbourhood total, and the Life rule is then two
bit patterns:

    total == 3                 -> born or survives
    total == 4 and was alive   -> survives

(`total` includes the cell itself, which is why the numbers are 3 and 4
rather than the 3 and 2 you see in the rules.)

Simulating a generation costs about 1800 integer ops. Drawing it costs
one `fill_region` per cell that *changed*, which is why the renderer
diffs against the previous generation instead of repainting the grid --
in a settled pattern that is a handful of cells, and the badge idles.
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
import random
import busio
import displayio
import fourwire
import terminalio
import neopixel
import adafruit_st7735r
from adafruit_display_text import label

# `bitmaptools` is a built-in module on the ESP32-S3 CircuitPython
# build. The pure-Python fallback keeps the sample running (slowly) on
# a build without it rather than crashing on import.
try:
    from bitmaptools import fill_region
except ImportError:
    def fill_region(bmp, x1, y1, x2, y2, value):
        for _y in range(y1, y2):
            for _x in range(x1, x2):
                bmp[_x, _y] = value


# ==================================================================
# Geometry. The display is 128 wide x 160 tall (portrait): the top
# 144 rows are the grid, the bottom 16 are one line of HUD.
# ==================================================================
CELL = 2                     # pixels per cell; 2 -> 64x72, 4 -> 32x36
COLS = 128 // CELL
ROWS = 144 // CELL
GRID_H = ROWS * CELL
HUD_Y = GRID_H

MASK = (1 << COLS) - 1       # one bit per column
LAST = COLS - 1


# ==================================================================
# Palette. Cells are drawn in four states so the eye can see which way
# the pattern is moving: a cell that has just appeared is bright, one
# that has just died leaves a dim ghost for a single generation.
# ==================================================================
BG = 0
ALIVE = 1
BORN = 2
GHOST = 3

palette = displayio.Palette(4)
palette[BG] = 0x080810
palette[ALIVE] = 0x2FBF5F
palette[BORN] = 0xC8FFD8
palette[GHOST] = 0x1B3A2A


# ==================================================================
# Seeds. '#' is a live cell, '.' is dead -- the same ASCII-art idiom
# the Doom sprites use. These are the standard published patterns;
# they are placed centred on the grid.
# ==================================================================
GLIDER_GUN = (
    "........................#...........",
    "......................#.#...........",
    "............##......##............##",
    "...........#...#....##............##",
    "##........#.....#...##..............",
    "##........#...#.##....#.#...........",
    "..........#.....#.......#...........",
    "...........#...#....................",
    "............##......................",
)

PULSAR = (
    "..###...###..",
    ".............",
    "#....#.#....#",
    "#....#.#....#",
    "#....#.#....#",
    "..###...###..",
    ".............",
    "..###...###..",
    "#....#.#....#",
    "#....#.#....#",
    "#....#.#....#",
    ".............",
    "..###...###..",
)

ACORN = (
    ".#.....",
    "...#...",
    "##..###",
)

R_PENTOMINO = (
    ".##",
    "##.",
    ".#.",
)

LWSS = (
    "#..#.",
    "....#",
    "#...#",
    ".####",
)

# (name, art or None for random soup)
SEEDS = (
    ("SOUP", None),
    ("GLIDER GUN", GLIDER_GUN),
    ("ACORN", ACORN),
    ("PULSAR", PULSAR),
    ("R-PENTOMINO", R_PENTOMINO),
    ("SPACESHIP", LWSS),
)


# ==================================================================
# Hardware
# ==================================================================
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.3, auto_write=False)


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
# Scene
# ==================================================================
scene = displayio.Group()

grid_bmp = displayio.Bitmap(COLS * CELL, GRID_H, 4)
scene.append(displayio.TileGrid(grid_bmp, pixel_shader=palette, x=0, y=0))

hud_bmp = displayio.Bitmap(128, 160 - HUD_Y, 2)
hud_pal = displayio.Palette(2)
hud_pal[0] = 0x000000
hud_pal[1] = 0x203040
scene.append(displayio.TileGrid(hud_bmp, pixel_shader=hud_pal, x=0, y=HUD_Y))

name_lbl = label.Label(terminalio.FONT, text="", color=0x60FFA0)
name_lbl.anchor_point = (0.0, 0.5)
name_lbl.anchored_position = (3, HUD_Y + 9)
scene.append(name_lbl)

stat_lbl = label.Label(terminalio.FONT, text="", color=0x808890)
stat_lbl.anchor_point = (1.0, 0.5)
stat_lbl.anchored_position = (125, HUD_Y + 9)
scene.append(stat_lbl)

display.root_group = scene

fill_region(hud_bmp, 0, 0, 128, 1, 1)        # hairline under the grid


# ==================================================================
# The simulation
# ==================================================================
def _triple(r):
    """Each cell plus its left and right neighbour, summed.

    Returns (ones, twos): the count at each bit position is
    `2*twos + ones`, so 0..3. The shifts wrap around the ends, which is
    what makes the grid a torus rather than a box -- a glider that
    leaves the right edge comes back in on the left.
    """
    left = ((r << 1) | (r >> LAST)) & MASK
    right = (r >> 1) | ((r & 1) << LAST)
    return (left ^ r ^ right,
            (left & r) | (left & right) | (r & right))


def life_step(rows):
    """One generation. `rows` is a list of ROWS ints, one bit per cell."""
    out = [0] * ROWS
    for y in range(ROWS):
        mid = rows[y]
        # rows[-1] is the last row, so the top edge wraps for free.
        up = rows[y - 1]
        dn = rows[y + 1] if y + 1 < ROWS else rows[0]

        # Three horizontal sums, each 0..3 as (ones, twos).
        a1, a2 = _triple(up)
        b1, b2 = _triple(mid)
        c1, c2 = _triple(dn)

        # Add the three "ones" words, and the three "twos" words,
        # carry-save style: XOR is the sum bit, majority is the carry.
        s1 = a1 ^ b1 ^ c1
        s2 = (a1 & b1) | (a1 & c1) | (b1 & c1)
        t2 = a2 ^ b2 ^ c2
        t4 = (a2 & b2) | (a2 & c2) | (b2 & c2)

        # Fold the two weight-2 words together, then the two weight-4.
        w2 = s2 ^ t2
        c4 = s2 & t2
        w4 = c4 ^ t4
        w8 = c4 & t4

        # The neighbourhood total (including the cell) is now binary
        # across s1/w2/w4/w8. Life needs only two of the sixteen cases.
        three = s1 & w2 & ~w4 & ~w8          # total == 3  -> 0b0011
        four = ~s1 & ~w2 & w4 & ~w8          # total == 4  -> 0b0100
        out[y] = (three | (mid & four)) & MASK
    return out


def population(rows):
    """Live cells. bin().count() beats any loop we could write here."""
    n = 0
    for r in rows:
        n += bin(r).count("1")
    return n


# ==================================================================
# Seeding
# ==================================================================
def _rand_row():
    v = 0
    bits = 0
    while bits < COLS:
        v |= random.getrandbits(16) << bits
        bits += 16
    return v & MASK


def soup():
    """Random fill at 3/8 density -- 1/2 burns down to ash too fast."""
    return [(_rand_row() | _rand_row()) & _rand_row() for _ in range(ROWS)]


def from_art(art):
    """Centre an ASCII pattern on an empty grid."""
    rows = [0] * ROWS
    h = len(art)
    w = len(art[0])
    y0 = (ROWS - h) // 2
    x0 = (COLS - w) // 2
    for j in range(h):
        line = art[j]
        bits = 0
        for i in range(w):
            if line[i] != ".":
                bits |= 1 << (x0 + i)
        rows[y0 + j] = bits & MASK
    return rows


def seed(idx):
    name, art = SEEDS[idx % len(SEEDS)]
    return name, (soup() if art is None else from_art(art))


# ==================================================================
# Renderer -- only the cells that changed.
# ==================================================================
def draw_all(rows):
    fill_region(grid_bmp, 0, 0, COLS * CELL, GRID_H, BG)
    for y in range(ROWS):
        r = rows[y]
        x = 0
        while r:
            if r & 1:
                fill_region(grid_bmp, x * CELL, y * CELL,
                            x * CELL + CELL, y * CELL + CELL, ALIVE)
            r >>= 1
            x += 1


def draw_diff(old, new, prev_born, prev_died):
    """Repaint only what changed, plus last generation's highlights.

    A cell drawn BORN or GHOST last time has to be repainted even if its
    state did not change this time, or the bright and dim marks would
    never fade.
    """
    born_rows = [0] * ROWS
    died_rows = [0] * ROWS
    for y in range(ROWS):
        o = old[y]
        n = new[y]
        born = n & ~o
        died = o & ~n
        born_rows[y] = born
        died_rows[y] = died

        todo = (born | died | prev_born[y] | prev_died[y]) & MASK
        if not todo:
            continue
        x = 0
        while todo:
            if todo & 1:
                bit = 1 << x
                if n & bit:
                    color = BORN if (born & bit) else ALIVE
                else:
                    color = GHOST if (died & bit) else BG
                fill_region(grid_bmp, x * CELL, y * CELL,
                            x * CELL + CELL, y * CELL + CELL, color)
            todo >>= 1
            x += 1
    return born_rows, died_rows


# ==================================================================
# LEDs -- population as a bar, so a dying grid visibly dims.
# ==================================================================
LED_FULL = COLS * ROWS * 0.16        # what counts as a "busy" grid


def update_leds(pop, flash=False):
    if flash:
        for i in range(5):
            pixels[i] = (120, 200, 255)
        pixels.show()
        return
    level = pop / LED_FULL * 5.0
    for i in range(5):
        v = level - i
        if v <= 0:
            pixels[i] = (0, 0, 0)
        else:
            if v > 1.0:
                v = 1.0
            pixels[i] = (int(20 * v), int(160 * v), int(70 * v))
    pixels.show()


# ==================================================================
# Main
# ==================================================================
SPEEDS = (0.0, 0.07, 0.2)            # seconds per generation
SPEED_NAMES = ("fast", "normal", "slow")

# A pattern that has settled into a still life or a period-2 blinker
# will never do anything again, and an unattended badge showing a
# frozen grid looks broken. Compare against the state one and two
# generations back and reseed when it stops moving.
STALL_LIMIT = 24
MAX_GENS = 1500                      # move on eventually regardless

try:
    random.seed(time.monotonic_ns())
except AttributeError:
    pass

seed_idx = 0
speed_idx = 1
paused = False

name, rows = seed(seed_idx)
prev1 = None
prev2 = None
prev_born = [0] * ROWS
prev_died = [0] * ROWS
gen = 0
stall = 0

draw_all(rows)
pop = population(rows)
name_lbl.text = name
stat_lbl.text = "gen 0"
display.refresh()
bl.value = True
update_leds(pop)

sw1_prev = sw2_prev = sw3_prev = True
next_at = time.monotonic()
hud_at = 0.0
print("GameOfLife: %dx%d grid, seed %s" % (COLS, ROWS, name))


def reseed(idx, why):
    global rows, prev1, prev2, prev_born, prev_died, gen, stall, name, pop
    name, rows = seed(idx)
    prev1 = prev2 = None
    prev_born = [0] * ROWS
    prev_died = [0] * ROWS
    gen = 0
    stall = 0
    draw_all(rows)
    pop = population(rows)
    name_lbl.text = name
    stat_lbl.text = "gen 0"
    display.refresh()
    update_leds(pop, flash=True)
    print("GameOfLife: %s -> %s" % (why, name))


while True:
    now = time.monotonic()

    # ---- buttons -------------------------------------------------
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    p1 = (not v1) and sw1_prev
    p2 = (not v2) and sw2_prev
    p3 = (not v3) and sw3_prev
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    if p1 and not paused:
        seed_idx += 1
        reseed(seed_idx, "SW1")
        continue
    if p2:
        paused = not paused
        stat_lbl.text = "paused" if paused else "gen %d" % gen
        display.refresh()
    if p3:
        speed_idx = (speed_idx + 1) % len(SPEEDS)
        name_lbl.text = "%s %s" % (name, SPEED_NAMES[speed_idx])
        display.refresh()

    if paused:
        # While paused SW1 becomes a single-step, which is the only way
        # to actually read a glider one generation at a time.
        if not p1:
            time.sleep(0.02)
            continue

    if now < next_at:
        time.sleep(0.002)
        continue
    next_at = now + SPEEDS[speed_idx]

    # ---- one generation ------------------------------------------
    new = life_step(rows)
    prev_born, prev_died = draw_diff(rows, new, prev_born, prev_died)
    prev2 = prev1
    prev1 = rows
    rows = new
    gen += 1
    display.refresh()

    # ---- has it stopped doing anything? --------------------------
    if rows == prev1 or (prev2 is not None and rows == prev2):
        stall += 1
    else:
        stall = 0

    if now - hud_at >= 0.4:
        hud_at = now
        pop = population(rows)
        stat_lbl.text = "gen %d  pop %d" % (gen, pop)
        update_leds(pop)

    if pop == 0:
        reseed(seed_idx + 1, "extinct")
        seed_idx += 1
    elif stall >= STALL_LIMIT:
        reseed(seed_idx + 1, "settled")
        seed_idx += 1
    elif gen >= MAX_GENS:
        reseed(seed_idx + 1, "time")
        seed_idx += 1
