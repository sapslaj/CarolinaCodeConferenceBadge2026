"""
code.py -- Wa-Tor World for the Carolina Code Conference 2026 badge.
====================================================================
Wa-Tor (A.K. Dewdney, 1984) is a predator/prey world on a torus. Fish
wander and breed; sharks hunt fish, breed more slowly, and starve if
they do not eat. Neither species ever settles -- the populations chase
each other up and down for as long as the badge is on.

This started as a port of the viewer frame from the `wa-tor-whirl`
browser toy and kept its rules, its colours and its habit of running
with no controls at all. The frame itself is gone: the world fills the
whole 128x160 panel, 64x80 cells drawn two pixels square, so what you
see is the grid itself rather than a canvas inside a border.

The rules are the page's rules, quirks included: *every* creature
spends one energy per move, so fish starve too, and a creature that is
boxed in on all four sides simply passes -- it neither ages nor breeds
that turn.

Why the numbers are not the page's
----------------------------------
The page runs 500 fish and 125 sharks on a 50x50 canvas and settles at
roughly half a full grid. Scaled up that would be thousands of
creatures a turn, which is more than this hardware wants to move, so
the biology here is retuned for a thinly populated ocean:

    world       64 x 80  (5120 cells, each drawn 2x2 px)
    speed       200 ms per turn
    fish        150 start, energy 42, breeds every 20 moves
    sharks       40 start, energy 12, breeds every 16 moves, meal = 12

The lever that sets how crowded the world gets is what a meal is
worth. A shark spends 1 energy a move and meets a fish on about
4 * (fish density) of its moves, so it only breaks even where
4 * density * meal >= 1: with the page's meal of 1 that needs a 25%
fish density, and with a meal of 12 it needs about 2%. Slowing fish
breeding down from every 2 moves to every 20 keeps them from simply
filling the empty space that leaves.

That holds about 260 creatures, some 5% of the grid, but it is Wa-Tor,
so it booms and crashes -- expect anything from a few dozen to a
couple of thousand. A world this size is also small enough for a bad
crash to finish it: they run about seven minutes before one species
loses and the next world starts. The 128x160 version of this world
lasted three times as long, which is the price of the bigger cells.

Controls
--------
None. The world runs by itself and reseeds when it is over: only
sharks left, only fish left, or open ocean.

How this is fast enough
-----------------------
The browser version keeps a list of creature objects and reads the
world back out of the canvas with `getImageData`. Neither idea
survives contact with a microcontroller: thousands of dict-ish objects
would eat the heap, and per-creature `findIndex` scans are quadratic.

So the world *is* the state here. `cells` is one flat array of 5120
16-bit words, and each creature is packed into a single word:

    bit 0-1   type   1 = fish, 2 = shark   (0 = open ocean)
    bit 2-6   fert   turns since it last bred   (0-31)
    bit 7-14  chi    energy left                (0-255)
    bit 15    stamp  "already took its turn this tick"

That is 10 KB as an `array("H")` against 20 KB as a list of Python
ints. The stamp bit flips its meaning every tick, which saves walking
the grid to clear it: a creature that moves into a cell the tick has
not reached yet is skipped rather than moving twice.

Three more things keep the tick cheap:

  * `cells` and the bitmap use the *same* flat index, so drawing a
    creature is one `bmp[idx]` store -- no index-to-(x, y) conversion,
    and the group's `scale` does the zoom to screen size in C.
  * The tick carries its own work list: every creature that survives
    appends where it ended up, so the next tick starts from a list of
    occupied cells instead of rescanning all 5120. Entries can go
    stale (eaten fish), which the stamp check already catches.
  * Fish outnumber sharks and only ever look for open water, so their
    neighbour scan is unrolled and skips the "is that prey?" test.

At a typical thousand creatures the turn costs far less than pushing
the frame out over SPI, so the viewer is limited by the panel rather
than by Python.
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
import neopixel
import adafruit_st7735r
from array import array


# ==================================================================
# The world's parameters. See the module docstring for why these are
# not the page's -- the short version is that a meal worth 30 is what
# lets sharks live in a thinly populated ocean.
# ==================================================================
COLS = 64                    # 64 x 80 cells drawn 2x2 -> the whole panel
ROWS = 80
CELL = 2                     # pixels per cell; COLS*CELL must be 128
PLAY_SPEED = 0.2             # seconds per turn

STARTING_FISH = 150
START_FISH_CHI = 42          # moves a fish lives without breeding
FISH_FERT_RATE = 20          # moves between calves  (max 31, 5 bits)
FISH_WEIGHT = 12             # energy a shark gains from a meal

STARTING_SHARKS = 40
START_SHARK_CHI = 12         # moves a shark lives between meals
SHARK_FERT_RATE = 16         # moves between pups    (max 31, 5 bits)

OCEAN = 0                    # also the empty-cell marker
FISH = 1
SHARK = 2

CELL_COUNT = COLS * ROWS
COLS_1 = COLS - 1
LAST_ROW = CELL_COUNT - COLS

# Creature packing (see the module docstring).
FERT_SHIFT = 2
CHI_SHIFT = 7
STAMP_BIT = 1 << 15
VALUE_MASK = STAMP_BIT - 1

# Newborns, pre-packed: type + full energy, fertility zero.
FISH_BABY = FISH | (START_FISH_CHI << CHI_SHIFT)
SHARK_BABY = SHARK | (START_SHARK_CHI << CHI_SHIFT)

# Colours lifted from the page's convertColor().
C_OCEAN = 0x0F41C8                   # rgba(15,65,200)
C_FISH = 0xE7CB6F                    # rgba(231,203,111)
C_SHARK = 0xB61919                   # rgba(182,25,25)

REPORT_EVERY = 50            # turns between population lines on serial


# ==================================================================
# Hardware
# ==================================================================
# The world has no LED display of its own; blank whatever the previous
# sample left lit.
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
# Scene -- one bitmap at world resolution, blown up to fill the panel.
#
# The bitmap stays 64x80 and a Group with `scale=CELL` doubles it to
# 128x160: displayio does the zoom in C, so drawing a creature is one
# store into a small bitmap rather than four stores into a big one.
# ==================================================================
palette = displayio.Palette(3)
palette[OCEAN] = C_OCEAN
palette[FISH] = C_FISH
palette[SHARK] = C_SHARK

grid_bmp = displayio.Bitmap(COLS, ROWS, 3)
scene = displayio.Group(scale=CELL)
scene.append(displayio.TileGrid(grid_bmp, pixel_shader=palette))
display.root_group = scene


# ==================================================================
# The world
# ==================================================================
# 16-bit words, one per cell. Built from a zero-filled bytes object so
# it never has to exist as a 5120-element Python list.
cells = array("H", bytes(2 * CELL_COUNT))

queue = []                   # where the creatures are, from last tick
mv = [0, 0, 0, 0]            # scratch: open neighbours
pv = [0, 0, 0, 0]            # scratch: neighbouring fish (sharks only)

stamp = 1                    # this tick's "already acted" mark
fish_pop = 0
shark_pop = 0


def populate():
    """Fill an empty ocean with fish, then sharks, never stacking two."""
    global fish_pop, shark_pop, stamp, queue

    for i in range(CELL_COUNT):
        cells[i] = 0
    grid_bmp.fill(OCEAN)

    # New creatures carry stamp 0, so the first tick (stamp 1) moves them.
    stamp = 1
    queue = []

    placed = 0
    while placed < STARTING_FISH:
        i = random.randrange(CELL_COUNT)
        if not cells[i]:
            cells[i] = FISH_BABY
            grid_bmp[i] = FISH
            queue.append(i)
            placed += 1

    placed = 0
    while placed < STARTING_SHARKS:
        i = random.randrange(CELL_COUNT)
        if not cells[i]:
            cells[i] = SHARK_BABY
            grid_bmp[i] = SHARK
            queue.append(i)
            placed += 1

    fish_pop = STARTING_FISH
    shark_pop = STARTING_SHARKS


def step():
    """One turn of the world -- popList() from the page, in one pass.

    Every creature standing at the start of the turn gets a move: eat
    if it can, breed if it is ready, otherwise wander. Cells are
    repainted as they change, so nothing redraws the whole grid.
    """
    global stamp, fish_pop, shark_pop, queue

    # Local aliases: in CircuitPython a global or attribute lookup
    # costs noticeably more than a local, and this loop runs once per
    # creature per turn.
    cells_ = cells
    bmp = grid_bmp
    rnd = random.randrange
    mv_ = mv
    pv_ = pv
    mark = stamp << 15
    fish = fish_pop
    sharks = shark_pop

    pending = queue
    nxt = []
    keep = nxt.append        # every survivor records where it ended up

    while pending:
        idx = pending.pop()
        c = cells_[idx]
        if not c or (c & STAMP_BIT) == mark:
            # Empty (its occupant moved away, or a shark ate it), or
            # already took its turn after moving in here.
            continue

        chi = (c >> CHI_SHIFT) & 255
        if chi == 0:
            # Out of energy: it dies where it stands.
            cells_[idx] = 0
            bmp[idx] = OCEAN
            if c & 3 == FISH:
                fish -= 1
            else:
                sharks -= 1
            continue

        ctype = c & 3
        fert = (c >> FERT_SHIFT) & 31

        # Four neighbours, wrapping -- the world is a torus. Only the
        # column has to be worked out; the row edges are just the ends
        # of the flat index.
        x = idx % COLS
        lf = idx - 1 if x else idx + COLS_1
        rt = idx + 1 if x < COLS_1 else idx - COLS_1
        up = idx - COLS if idx >= COLS else idx + LAST_ROW
        dn = idx + COLS if idx < LAST_ROW else idx - LAST_ROW

        nopen = 0
        nprey = 0
        if ctype == SHARK:
            # Sharks are the rare case, so readability wins.
            for n in (lf, rt, dn, up):
                t = cells_[n]
                if not t:
                    mv_[nopen] = n
                    nopen += 1
                elif t & 3 == FISH:
                    pv_[nprey] = n
                    nprey += 1
        else:
            # Fish are the common case and only want open water; this
            # is unrolled on purpose -- no loop, no tuple, no type test.
            if not cells_[lf]:
                mv_[nopen] = lf
                nopen += 1
            if not cells_[rt]:
                mv_[nopen] = rt
                nopen += 1
            if not cells_[dn]:
                mv_[nopen] = dn
                nopen += 1
            if not cells_[up]:
                mv_[nopen] = up
                nopen += 1

        # A shark takes a fish if one is adjacent; otherwise anything
        # alive moves into open water. One candidate needs no dice.
        if nprey:
            n = pv_[0] if nprey == 1 else pv_[rnd(nprey)]
        elif nopen:
            n = mv_[0] if nopen == 1 else mv_[rnd(nopen)]
        else:
            # Boxed in. The page pushes it back unchanged -- no move,
            # no energy spent, no fertility gained.
            cells_[idx] = (c & VALUE_MASK) | mark
            keep(idx)
            continue

        # Breeding: the parent leaves a newborn in the cell it vacates.
        baby = 0
        if ctype == FISH:
            if fert >= FISH_FERT_RATE:
                baby = FISH_BABY | mark
                fert = 0
                fish += 1
        elif fert >= SHARK_FERT_RATE:
            baby = SHARK_BABY | mark
            fert = 0
            sharks += 1

        if nprey:
            # Only a shark gets here, and only onto a fish.
            chi += FISH_WEIGHT
            if chi > 255:
                chi = 255
            fish -= 1

        # Vacate the cell. A newborn wears its parent's colour, so the
        # pixel is already right and only an empty cell needs redrawing.
        cells_[idx] = baby
        if baby:
            keep(idx)
        else:
            bmp[idx] = OCEAN

        fert += 1
        chi -= 1
        cells_[n] = ctype | (fert << FERT_SHIFT) | (chi << CHI_SHIFT) | mark
        bmp[n] = ctype
        keep(n)

    queue = nxt
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
display.refresh()
bl.value = True

turn = 0
print("WaTor: %dx%d world, %d fish, %d sharks"
      % (COLS, ROWS, fish_pop, shark_pop))

while True:
    started = time.monotonic()

    step()
    display.refresh()

    turn += 1
    if turn % REPORT_EVERY == 0:
        # No room for a tally on screen any more -- the world owns
        # every pixel -- so the populations go to the serial console.
        print("WaTor: turn %d  fish %d  sharks %d" % (turn, fish_pop, shark_pop))

    # The page stops when the world empties or fills; with no Restart
    # button, start a fresh world instead. It takes both species to
    # make a Wa-Tor world worth watching, so the moment one of them is
    # gone -- all sharks, all fish, or open ocean -- this one is over.
    if fish_pop == 0:
        why = "ocean" if shark_pop == 0 else "sharks only"
    elif shark_pop == 0:
        why = "fish only"
    elif fish_pop + shark_pop >= CELL_COUNT:
        why = "world full"
    else:
        why = None

    if why:
        print("WaTor: %s after %d turns -- reseeding" % (why, turn))
        time.sleep(0.5)
        populate()
        turn = 0
        display.refresh()
        continue

    # Hold the turn length when there is slack; a crowded world simply
    # runs as fast as the badge can draw it.
    slack = PLAY_SPEED - (time.monotonic() - started)
    if slack > 0:
        time.sleep(slack)
