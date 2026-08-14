"""
code.py -- Wa-Tor World viewer for the Carolina Code Conference 2026 badge.
==========================================================================
A port of the viewer frame from the `wa-tor-whirl` browser toy: the
world canvas, its border, the size readout and the fish/shark tally.
The sidebar, the play/pause/restart buttons and every input box are
gone -- this runs the simulation with the page's default variables and
nothing else.

Wa-Tor (A.K. Dewdney, 1984) is a predator/prey world on a torus. Fish
wander and breed; sharks hunt fish, breed more slowly, and starve if
they do not eat. Populations chase each other up and down forever.

The defaults, straight from the page
------------------------------------
    world       50 x 50   (500px canvas / 10px cells)
    speed       100 ms per turn
    fish        500 start, energy 5, fertility 2, weight 1
    sharks      125 start, energy 4, fertility 8

The rules are the page's rules, quirks included: *every* creature
spends one energy per move, so fish starve too, and a creature that is
boxed in on all four sides simply passes -- it neither ages nor breeds
that turn.

Controls
--------
None. The viewer runs by itself. Because there is no Restart button to
press, the world reseeds on its own when it ends: everything dead, the
grid completely full, or one species gone long enough that nothing
interesting is left to watch.

How this is fast enough
-----------------------
The browser version keeps a list of creature objects and reads the
world back out of the canvas with `getImageData`. Neither idea
survives contact with a microcontroller: 2500 dict-ish objects would
eat the heap, and per-creature `findIndex` scans are quadratic.

So the world *is* the state here. `cells` is one flat list of 2500
small integers, and each creature is packed into a single int:

    bit 0-1   type   1 = fish, 2 = shark   (0 = open ocean)
    bit 2-6   fert   turns since it last bred
    bit 7-14  chi    energy left
    bit 15    stamp  "already took its turn this tick"

Small ints live inline in the list, so a full world costs one list of
2500 slots rather than 2500 objects, and looking up "what is in the
cell to my left" is one index. The stamp bit flips its meaning every
tick, which saves walking the grid to clear it: a creature that moves
into a cell that has not been visited yet this tick is skipped rather
than moving twice.
"""

# --- backlight off FIRST, before the slow adafruit imports ---------
# The panel powers up bright white, so claim IO5 and drive it low
# before spending seconds on imports.
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
# The page's default variables, unchanged.
# ==================================================================
COLS = 50                    # 500px canvas / 10px pixelSize
ROWS = 50
PLAY_SPEED = 0.1             # playSpeed, 100 ms

STARTING_FISH = 500
START_FISH_CHI = 5
FISH_FERT_RATE = 2
FISH_WEIGHT = 1

STARTING_SHARKS = 125
START_SHARK_CHI = 4
SHARK_FERT_RATE = 8

OCEAN = 0                    # also the empty-cell marker
FISH = 1
SHARK = 2

CELL = 2                     # badge pixels per world cell -> 100x100
CELL_COUNT = COLS * ROWS
COLS_1 = COLS - 1
ROWS_1 = ROWS - 1
LAST_ROW = CELL_COUNT - COLS

# Creature packing (see the module docstring).
FERT_SHIFT = 2
CHI_SHIFT = 7
STAMP_BIT = 1 << 15
VALUE_MASK = STAMP_BIT - 1

# There is no Restart button, so the viewer restarts itself.
EXTINCT_GRACE = 60           # ticks a lone species is allowed to coast


# ==================================================================
# Layout -- the viewer frame, on a 128x160 portrait panel.
#
#   WA-TOR              title
#   WORLD  50 x 50      size readout
#   +----------------+  3px border, the page's .world-wrap
#   |   100 x 100    |  the canvas
#   +----------------+
#   fish 500  sharks 125
# ==================================================================
GRID_W = COLS * CELL
GRID_H = ROWS * CELL
GRID_X = (128 - GRID_W) // 2         # 14
GRID_Y = 39
BORDER = 3
FRAME_X0 = GRID_X - BORDER
FRAME_Y0 = GRID_Y - BORDER
FRAME_X1 = GRID_X + GRID_W + BORDER
FRAME_Y1 = GRID_Y + GRID_H + BORDER

# Colours lifted from the stylesheet / convertColor().
C_OCEAN = 0x0F41C8                   # rgba(15,65,200)
C_FISH = 0xE7CB6F                    # rgba(231,203,111)
C_SHARK = 0xB61919                   # rgba(182,25,25)
C_TEXT = 0xC8DCFA                    # rgba(200,220,250)
C_FISH_TEXT = 0xE7CB6F
C_SHARK_TEXT = 0xE05A5A              # the shark red, lifted to stay legible
C_FRAME = 0x29336A                   # .world-wrap border over the backdrop
BG_TOP = (5, 5, 65)                  # body gradient, rgba(5,5,65)
BG_BOTTOM = (35, 65, 110)            # ...to rgba(35,65,110)
BG_STEPS = 8


# ==================================================================
# Hardware
# ==================================================================
# The viewer has no LED display of its own; blank whatever the
# previous sample left lit.
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.2, auto_write=False)
pixels.fill((0, 0, 0))
pixels.show()

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

# Backdrop: the page's diagonal body gradient, flattened to a vertical
# ramp in BG_STEPS bands, plus one more entry for the canvas border.
bg_pal = displayio.Palette(BG_STEPS + 1)
for i in range(BG_STEPS):
    f = i / (BG_STEPS - 1)
    r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * f)
    g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * f)
    b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * f)
    bg_pal[i] = (r << 16) | (g << 8) | b
bg_pal[BG_STEPS] = C_FRAME

bg_bmp = displayio.Bitmap(128, 160, BG_STEPS + 1)
band = 160 // BG_STEPS
for i in range(BG_STEPS):
    fill_region(bg_bmp, 0, i * band, 128, (i + 1) * band, i)
# The border is drawn solid; the grid sits on top and covers the middle.
fill_region(bg_bmp, FRAME_X0, FRAME_Y0, FRAME_X1, FRAME_Y1, BG_STEPS)
scene.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))

grid_pal = displayio.Palette(3)
grid_pal[OCEAN] = C_OCEAN
grid_pal[FISH] = C_FISH
grid_pal[SHARK] = C_SHARK
grid_bmp = displayio.Bitmap(GRID_W, GRID_H, 3)
scene.append(displayio.TileGrid(grid_bmp, pixel_shader=grid_pal,
                                x=GRID_X, y=GRID_Y))

title_lbl = label.Label(terminalio.FONT, text="WA-TOR", scale=2, color=C_TEXT)
title_lbl.anchor_point = (0.5, 0.5)
title_lbl.anchored_position = (64, 12)
scene.append(title_lbl)

size_lbl = label.Label(terminalio.FONT, color=C_TEXT,
                       text="WORLD  %d x %d" % (COLS, ROWS))
size_lbl.anchor_point = (0.5, 0.5)
size_lbl.anchored_position = (64, 28)
scene.append(size_lbl)

fish_lbl = label.Label(terminalio.FONT, text="", color=C_FISH_TEXT)
fish_lbl.anchor_point = (0.0, 0.5)
fish_lbl.anchored_position = (4, 151)
scene.append(fish_lbl)

shark_lbl = label.Label(terminalio.FONT, text="", color=C_SHARK_TEXT)
shark_lbl.anchor_point = (1.0, 0.5)
shark_lbl.anchored_position = (124, 151)
scene.append(shark_lbl)

display.root_group = scene


# ==================================================================
# The world
# ==================================================================
cells = [0] * CELL_COUNT
mv = [0, 0, 0, 0]            # scratch: open neighbours
pv = [0, 0, 0, 0]            # scratch: neighbouring fish (sharks only)

stamp = 1                    # this tick's "already acted" mark
fish_pop = 0
shark_pop = 0


def paint(idx, value):
    """Draw one world cell, addressed by flat index."""
    y = idx // COLS
    x = idx - y * COLS
    fill_region(grid_bmp, x * CELL, y * CELL,
                x * CELL + CELL, y * CELL + CELL, value)


def populate():
    """Fill an empty ocean with fish, then sharks, never stacking two."""
    global fish_pop, shark_pop, stamp

    for i in range(CELL_COUNT):
        cells[i] = 0
    fill_region(grid_bmp, 0, 0, GRID_W, GRID_H, OCEAN)

    # New creatures carry stamp 0, so the first tick (stamp 1) moves them.
    stamp = 1

    placed = 0
    while placed < STARTING_FISH:
        i = random.randrange(CELL_COUNT)
        if not cells[i]:
            cells[i] = FISH | (START_FISH_CHI << CHI_SHIFT)
            paint(i, FISH)
            placed += 1

    placed = 0
    while placed < STARTING_SHARKS:
        i = random.randrange(CELL_COUNT)
        if not cells[i]:
            cells[i] = SHARK | (START_SHARK_CHI << CHI_SHIFT)
            paint(i, SHARK)
            placed += 1

    fish_pop = STARTING_FISH
    shark_pop = STARTING_SHARKS


def step():
    """One turn of the world -- popList() from the page, in one pass.

    Every creature standing at the start of the tick gets a move: eat
    if it can, breed if it is ready, otherwise wander. Cells are
    repainted as they change, so nothing redraws the whole grid.
    """
    global stamp, fish_pop, shark_pop

    # Local aliases: attribute and global lookups are the expensive
    # part of a CircuitPython inner loop, and this one runs ~1000x
    # per tick.
    cells_ = cells
    fill = fill_region
    bmp = grid_bmp
    rnd = random.randrange
    mv_ = mv
    pv_ = pv
    mark = stamp << 15
    fish = fish_pop
    sharks = shark_pop

    queue = [i for i in range(CELL_COUNT) if cells_[i]]

    while queue:
        idx = queue.pop()
        c = cells_[idx]
        if not c or (c & STAMP_BIT) == mark:
            # Empty (eaten, or its occupant moved away), or already
            # took its turn after moving in here.
            continue

        ctype = c & 3
        fert = (c >> FERT_SHIFT) & 31
        chi = (c >> CHI_SHIFT) & 255

        y = idx // COLS
        x = idx - y * COLS
        gx = x * CELL
        gy = y * CELL

        if chi == 0:
            # Out of energy: it dies where it stands.
            cells_[idx] = 0
            fill(bmp, gx, gy, gx + CELL, gy + CELL, OCEAN)
            if ctype == FISH:
                fish -= 1
            else:
                sharks -= 1
            continue

        # Four neighbours, wrapping -- the world is a torus.
        up = idx - COLS if y else idx + LAST_ROW
        dn = idx + COLS if y < ROWS_1 else x
        lf = idx - 1 if x else idx + COLS_1
        rt = idx + 1 if x < COLS_1 else idx - COLS_1

        nopen = 0
        nprey = 0
        for n in (lf, rt, dn, up):
            t = cells_[n]
            if not t:
                mv_[nopen] = n
                nopen += 1
            elif ctype == SHARK and (t & 3) == FISH:
                pv_[nprey] = n
                nprey += 1

        # A shark takes a fish if one is adjacent; otherwise anything
        # alive moves into open water.
        if nprey:
            n = pv_[rnd(nprey)]
        elif nopen:
            n = mv_[rnd(nopen)]
        else:
            # Boxed in. The page pushes it back unchanged -- no move,
            # no energy spent, no fertility gained.
            cells_[idx] = (c & VALUE_MASK) | mark
            continue

        # Breeding: the parent leaves a newborn in the cell it vacates.
        baby = 0
        if ctype == FISH:
            if fert >= FISH_FERT_RATE:
                baby = FISH | (START_FISH_CHI << CHI_SHIFT) | mark
                fert = 0
                fish += 1
        elif fert >= SHARK_FERT_RATE:
            baby = SHARK | (START_SHARK_CHI << CHI_SHIFT) | mark
            fert = 0
            sharks += 1

        if nprey:
            # Only a shark gets here, and only onto a fish.
            chi += FISH_WEIGHT
            if chi > 255:
                chi = 255
            fish -= 1

        # Vacate: ocean, or the newborn. `baby & 3` is its palette index.
        cells_[idx] = baby
        fill(bmp, gx, gy, gx + CELL, gy + CELL, baby & 3)

        fert += 1
        chi -= 1
        cells_[n] = ctype | (fert << FERT_SHIFT) | (chi << CHI_SHIFT) | mark
        ny = n // COLS
        nx = n - ny * COLS
        fill(bmp, nx * CELL, ny * CELL,
             nx * CELL + CELL, ny * CELL + CELL, ctype)

    stamp ^= 1
    fish_pop = fish
    shark_pop = sharks


# ==================================================================
# Main
# ==================================================================
try:
    random.seed(time.monotonic_ns())
except AttributeError:
    pass

populate()
fish_lbl.text = "fish %d" % fish_pop
shark_lbl.text = "sharks %d" % shark_pop
display.refresh()
bl.value = True

shown_fish = fish_pop
shown_sharks = shark_pop
lonely = 0
print("WaTor: %dx%d world, %d fish, %d sharks"
      % (COLS, ROWS, fish_pop, shark_pop))

while True:
    started = time.monotonic()

    step()

    if fish_pop != shown_fish:
        shown_fish = fish_pop
        fish_lbl.text = "fish %d" % fish_pop
    if shark_pop != shown_sharks:
        shown_sharks = shark_pop
        shark_lbl.text = "sharks %d" % shark_pop
    display.refresh()

    # The page stops when the world empties or fills; with no Restart
    # button, start a fresh world instead. A world down to one species
    # is given a little rope first -- fish alone just grow to the edges.
    total = fish_pop + shark_pop
    if fish_pop == 0 or shark_pop == 0:
        lonely += 1
    else:
        lonely = 0

    if total == 0:
        why = "extinct"
    elif total >= CELL_COUNT:
        why = "world full"
    elif lonely >= EXTINCT_GRACE:
        why = "one species left"
    else:
        why = None

    if why:
        print("WaTor: %s -- reseeding" % why)
        time.sleep(0.5)
        populate()
        shown_fish = fish_pop
        shown_sharks = shark_pop
        fish_lbl.text = "fish %d" % fish_pop
        shark_lbl.text = "sharks %d" % shark_pop
        lonely = 0
        display.refresh()
        continue

    # Hold the page's 100 ms turn when there is slack; a busy world
    # simply runs as fast as the badge can draw it.
    slack = PLAY_SPEED - (time.monotonic() - started)
    if slack > 0:
        time.sleep(slack)
