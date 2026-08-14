"""
code.py -- "FACTORIO" self-building factory for the Carolina Code Conference 2026 badge.
=======================================================================================
A top-down factory that builds itself. Mining drills chew ore out of the
ground, furnaces smelt it into plates, a main bus belt carries the plates
past assemblers that pull off what they need, and a lab at the end of the
line turns gears and circuits into research.

Nobody has to touch it. Every time enough material piles up in the storage
chest -- or a research finishes -- the next machine gets built and the
factory grows. When the last research lands the factory is complete, the
badge celebrates, and the whole thing starts over from one lonely drill.

This is NOT Wube's Factorio -- see README.md. It is the badge's own take on
the idea, and the idea is the tagline: the factory must grow.

Controls
--------
  SW1  -- toggle ALT-MODE (item labels on the machines, like the real game)
  SW2  -- hold for 3x speed
  SW3  -- tear it down and start a fresh factory

Rendering
---------
The factory is one 128x120 indexed `displayio.Bitmap` and every pixel that
changes is written by `bitmaptools.fill_region`, which fills a rectangle in
C. Nothing is plotted pixel-by-pixel from Python -- that is the whole
performance trick, the same one the Doom sample uses.

The floor, ore patches and machine shells only change when a structure
appears, so they are painted once into the bitmap and left alone. Each
frame repaints just the moving parts: belt lanes, the items riding them,
inserter arms, and the small animated panel inside each machine. That is
roughly 170 rectangle fills per frame instead of 400.

Geometry note: every belt is axis-aligned. `Belt` measures length as
|dx| + |dy| per segment, which is only the true distance for horizontal
and vertical runs -- do not add a diagonal waypoint.
"""

# --- backlight off FIRST, before the slow adafruit imports ---------
# Same trick the launcher uses: the panel powers up bright white, so
# claim IO5 and drive it low before spending seconds on imports.
import board
import digitalio
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

import math
import time
import random
import busio
import displayio
import fourwire
import terminalio
import neopixel
import adafruit_st7735r
from adafruit_display_text import label

# `bitmaptools` is a built-in module on the ESP32-S3 CircuitPython build.
# The pure-Python fallback keeps the demo running (very slowly) on a build
# without it rather than crashing on import.
try:
    from bitmaptools import fill_region
except ImportError:
    def fill_region(bmp, x1, y1, x2, y2, value):
        for _y in range(y1, y2):
            for _x in range(x1, x2):
                bmp[_x, _y] = value


# ==================================================================
# Screen layout -- the display is 128 wide x 160 tall (portrait).
# The top 120 rows are the factory floor, the bottom 40 are the HUD.
# ==================================================================
VW = 128
VH = 120
HUD_H = 160 - VH


# ==================================================================
# Items. Six kinds ride the belts; science packs are never an item --
# the lab consumes ingredients directly (see README.md).
# ==================================================================
FE_ORE, CU_ORE, FE_PLATE, CU_PLATE, GEAR, CHIP = 0, 1, 2, 3, 4, 5
N_ITEMS = 6


# ==================================================================
# Palette. The floor bitmap stores palette indices, so every colour the
# renderer can draw has to be allocated up front.
# ==================================================================
FLOOR = 0
FLOOR_LINE = 1
ORE_FE = 2
ORE_CU = 3
BELT_FRAME = 4
BELT_LANE = 5
BELT_TREAD = 6
GHOST_FILL = 7
GHOST_LINE = 8
METAL = 9
METAL_D = 10
METAL_L = 11
YELLOW = 12
ORANGE = 13
FIRE = 14
BRICK = 15
ASM_BODY = 16
GLASS = 17
GLASS_HOT = 18
LAB_BODY = 19
SCI_RED = 20
SCI_GRN = 21
IT_FE_ORE = 22
IT_CU_ORE = 23
IT_FE_PLT = 24
IT_CU_PLT = 25
IT_GEAR = 26
IT_CHIP = 27
BEACON_C = 28
SHADOW = 29
PAL_LEN = 30

palette = displayio.Palette(PAL_LEN)
palette[FLOOR] = 0x2E2E33          # bare concrete
palette[FLOOR_LINE] = 0x36363C     # faint grid so the empty floor has scale
palette[ORE_FE] = 0x6E7C8E
palette[ORE_CU] = 0xA5643A
palette[BELT_FRAME] = 0x26262A
palette[BELT_LANE] = 0x8A7326      # the yellow transport belt
palette[BELT_TREAD] = 0xD9C24F
palette[GHOST_FILL] = 0x1C2C3A     # unbuilt: a blueprint ghost
palette[GHOST_LINE] = 0x2F86C4
palette[METAL] = 0x9AA0A8
palette[METAL_D] = 0x5C6068
palette[METAL_L] = 0xC8CED6
palette[YELLOW] = 0xD8B23A
palette[ORANGE] = 0xE8721C
palette[FIRE] = 0xFFB43C
palette[BRICK] = 0x7A4030
palette[ASM_BODY] = 0x4E5A6A
palette[GLASS] = 0x53819A
palette[GLASS_HOT] = 0x9FDDF4
palette[LAB_BODY] = 0xB4B8BE
palette[SCI_RED] = 0xD8404A
palette[SCI_GRN] = 0x56C85A
palette[IT_FE_ORE] = 0x8B99AB
palette[IT_CU_ORE] = 0xC07A44
palette[IT_FE_PLT] = 0xD6DEE6
palette[IT_CU_PLT] = 0xE8A05A
palette[IT_GEAR] = 0x8E949C
palette[IT_CHIP] = 0x3FC85F
palette[BEACON_C] = 0x39D4E0
palette[SHADOW] = 0x1A1A1E

ITEM_COLOR = (IT_FE_ORE, IT_CU_ORE, IT_FE_PLT, IT_CU_PLT, IT_GEAR, IT_CHIP)


# ==================================================================
# Simulation tunables
# ==================================================================
BELT_SPEED = 26.0        # pixels / second
TREAD_PITCH = 6.0        # spacing of the moving chevrons
ITEM_GAP = 7.0           # closest two items may sit on a belt
GRAB_TOL = 5.0           # how far either side of itself an inserter reaches
INSERTER_TIME = 0.30     # seconds per swing
BUF_CAP = 4              # ingredients a machine will hoard

DRILL_TIME = 0.75
FURNACE_TIME = 0.90
GEAR_TIME = 1.40
CHIP_TIME = 1.60

POWER_SUPPLY = 85        # one boiler + one steam engine, and that is all

BELT_HALF = 4            # belt frame half-width (9 px total)
LANE_HALF = 3            # moving lane half-width (7 px total)
ITEM_SIZE = 5


# ==================================================================
# Belt -- a polyline of axis-aligned segments carrying items.
#
# `items` is kept sorted by position, front (largest) first, which makes
# spacing a single comparison against the item ahead. That ordering is
# also what lets a full belt back up: nothing may pass the thing in
# front of it, so a slow consumer stalls the whole line behind it,
# exactly like the real game.
# ==================================================================
class Belt:
    def __init__(self, points):
        self.points = tuple(points)
        segs = []
        total = 0.0
        for i in range(len(self.points) - 1):
            x0, y0 = self.points[i]
            x1, y1 = self.points[i + 1]
            dx = x1 - x0
            dy = y1 - y0
            ln = float(abs(dx) + abs(dy))       # axis-aligned only
            segs.append((total, x0, y0, dx / ln, dy / ln, ln))
            total += ln
        self.segs = tuple(segs)
        self.length = total
        self.items = []          # [[pos, kind], ...] front first

    def clear(self):
        self.items = []

    def advance(self, dist):
        """Move every item forward, none passing the one ahead of it."""
        limit = self.length
        for it in self.items:
            p = it[0] + dist
            if p > limit:
                p = limit
            it[0] = p
            limit = p - ITEM_GAP

    def try_insert(self, pos, kind):
        """Put an item on at `pos`, or refuse if that stretch is occupied."""
        items = self.items
        idx = 0
        n = len(items)
        while idx < n and items[idx][0] > pos:
            idx += 1
        if idx > 0 and items[idx - 1][0] - pos < ITEM_GAP:
            return False
        if idx < n and pos - items[idx][0] < ITEM_GAP:
            return False
        items.insert(idx, [pos, kind])
        return True

    def take_near(self, pos, wanted):
        """Remove and return the first wanted item within reach of `pos`,
        or -1. Items are ordered front-first, so once we are past the
        window there is nothing left to find."""
        items = self.items
        lo = pos - GRAB_TOL
        hi = pos + GRAB_TOL
        for i in range(len(items)):
            p = items[i][0]
            if p < lo:
                return -1
            if p <= hi and items[i][1] in wanted:
                return items.pop(i)[1]
        return -1

    def front_at_end(self):
        """Kind of the item parked at the very end of the belt, or -1."""
        items = self.items
        if items and items[0][0] >= self.length - 0.5:
            return items[0][1]
        return -1

    def take_end(self):
        return self.items.pop(0)[1]

    def point_at(self, pos):
        for (base, x0, y0, ux, uy, ln) in self.segs:
            if pos <= base + ln:
                d = pos - base
                return x0 + ux * d, y0 + uy * d
        base, x0, y0, ux, uy, ln = self.segs[-1]
        return x0 + ux * ln, y0 + uy * ln


# ==================================================================
# Machine -- one structure on the floor.
#
# Every machine is the same three steps (take inputs, craft, push the
# result out); what differs is only the plumbing, so that lives in
# fields rather than in subclasses. A machine with no `inputs` is a
# drill (it mines from nothing); one with no `out` is the lab (its
# output is research, which is not an item).
# ==================================================================
class Machine:
    def __init__(self, kind, rect, power=0, passive=False):
        self.kind = kind
        self.x0, self.y0, self.x1, self.y1 = rect
        self.cx = (self.x0 + self.x1) // 2
        self.cy = (self.y0 + self.y1) // 2
        self.power = power
        self.passive = passive       # decor: boiler, engine, beacon, chest
        self.built = False

        self.inputs = ()             # ((kind, count), ...)
        self.out = -1                # item kind produced, -1 = research
        self.craft_time = 1.0

        self.eat_end = None          # belt whose END drops straight into us
        self.in_belt = None          # belt an inserter picks off
        self.in_pos = 0.0
        self.ins_rect = None         # arm channel (x0, y0, x1, y1)
        self.ins_vertical = True
        self.out_belt = None
        self.out_pos = 0.0

        self.buf = bytearray(N_ITEMS)
        self.progress = 0.0
        self.crafting = False
        self.holding = False         # finished item waiting for belt room
        self.blocked = False
        self.count = 0               # crafts completed since the last reset
        self.arm_cool = 0.0
        self.arm_item = -1

    def reset(self):
        self.built = False
        for i in range(N_ITEMS):
            self.buf[i] = 0
        self.progress = 0.0
        self.crafting = False
        self.holding = False
        self.blocked = False
        self.count = 0
        self.arm_cool = 0.0
        self.arm_item = -1

    def recipe(self, inputs, out, craft_time):
        self.inputs = inputs
        self.out = out
        self.craft_time = craft_time

    # -- one simulation step; returns True on a completed craft --------
    def tick(self, dt):
        if not self.built or self.passive:
            return False

        # Fed by a belt that dead-ends in our wall (drill -> furnace).
        if self.eat_end is not None:
            k = self.eat_end.front_at_end()
            if k >= 0 and self.buf[k] < BUF_CAP:
                self.eat_end.take_end()
                self.buf[k] += 1

        # Fed by an inserter reaching over to the main bus.
        if self.in_belt is not None:
            if self.arm_cool > 0.0:
                self.arm_cool -= dt
                if self.arm_cool <= 0.0 and self.arm_item >= 0:
                    self.buf[self.arm_item] += 1
                    self.arm_item = -1
            else:
                wanted = []
                for (k, _n) in self.inputs:
                    if self.buf[k] < BUF_CAP:
                        wanted.append(k)
                if wanted:
                    got = self.in_belt.take_near(self.in_pos, tuple(wanted))
                    if got >= 0:
                        self.arm_item = got
                        self.arm_cool = INSERTER_TIME

        if self.holding:
            self._flush()

        if not self.crafting and not self.holding:
            ready = True
            for (k, n) in self.inputs:
                if self.buf[k] < n:
                    ready = False
                    break
            if ready:
                for (k, n) in self.inputs:
                    self.buf[k] -= n
                self.crafting = True
                self.progress = 0.0

        if self.crafting:
            self.progress += dt / self.craft_time
            if self.progress >= 1.0:
                self.crafting = False
                self.progress = 0.0
                self.count += 1
                if self.out >= 0:
                    self.holding = True
                    self._flush()
                return True
        return False

    def _flush(self):
        if self.out_belt is None:
            self.holding = False
            return
        if self.out_belt.try_insert(self.out_pos, self.out):
            self.holding = False
            self.blocked = False
        else:
            self.blocked = True      # output full -- stall, like the game


# ==================================================================
# The floor plan. Hand-placed so that nothing overlaps anything: every
# belt run has a 9 px frame, and the gaps left between a belt and the
# machine beside it are the channels the inserter arms swing in.
# ==================================================================
#            kind        rect                        power
drill_fe = Machine("drill", (2, 2, 28, 24), 12)
furn_fe = Machine("furnace", (48, 2, 74, 24), 8)
drill_cu = Machine("drill", (2, 28, 28, 50), 12)
furn_cu = Machine("furnace", (48, 28, 74, 50), 8)
asm_gear = Machine("asm", (52, 72, 80, 92), 10)
asm_circ = Machine("asm", (84, 72, 112, 92), 10)
lab = Machine("lab", (20, 72, 48, 94), 14)
chest = Machine("chest", (94, 100, 118, 118), 0, passive=True)
boiler = Machine("boiler", (82, 44, 98, 58), 0, passive=True)
engine = Machine("engine", (100, 44, 114, 58), 0, passive=True)
beacon = Machine("beacon", (86, 18, 108, 34), 20, passive=True)

STRUCTURES = (drill_fe, furn_fe, drill_cu, furn_cu, boiler, engine,
              beacon, lab, asm_gear, asm_circ, chest)

BY_NAME = {
    "drill_fe": drill_fe, "furn_fe": furn_fe,
    "drill_cu": drill_cu, "furn_cu": furn_cu,
    "asm_gear": asm_gear, "asm_circ": asm_circ,
    "lab": lab, "chest": chest,
    "boiler": boiler, "engine": engine, "beacon": beacon,
}

# Short ore belts from each drill into its furnace...
belt_fe_ore = Belt(((28, 13), (48, 13)))
belt_cu_ore = Belt(((28, 39), (48, 39)))
# ...a feeder carrying copper plates east to join the bus...
belt_cu_plate = Belt(((74, 39), (116, 39)))
# ...and the main bus, which snakes from the iron furnace all the way
# down to the storage chest, passing every consumer on the way.
bus = Belt(((74, 13), (120, 13), (120, 63), (10, 63), (10, 110), (92, 110)))

BELTS = (belt_fe_ore, belt_cu_ore, belt_cu_plate, bus)

# Bus positions, measured along the polyline above. Each assembler grabs
# at its own doorstep and drops its product a few pixels downstream so
# the thing it just made cannot be picked straight back up.
BUS_CU_MERGE = 72.0      # where the copper feeder tips onto the bus
BUS_CIRC_IN = 118.0
BUS_CIRC_OUT = 124.0
BUS_GEAR_IN = 152.0
BUS_GEAR_OUT = 158.0
BUS_LAB_IN = 225.0

# Recipes and plumbing. Drills mine from the patch under them, so they
# have no inputs at all -- they are pure sources.
drill_fe.recipe((), FE_ORE, DRILL_TIME)
drill_fe.out_belt = belt_fe_ore
drill_fe.out_pos = 0.0

drill_cu.recipe((), CU_ORE, DRILL_TIME)
drill_cu.out_belt = belt_cu_ore
drill_cu.out_pos = 0.0

furn_fe.recipe(((FE_ORE, 1),), FE_PLATE, FURNACE_TIME)
furn_fe.eat_end = belt_fe_ore
furn_fe.out_belt = bus
furn_fe.out_pos = 0.0

furn_cu.recipe(((CU_ORE, 1),), CU_PLATE, FURNACE_TIME)
furn_cu.eat_end = belt_cu_ore
furn_cu.out_belt = belt_cu_plate
furn_cu.out_pos = 0.0

asm_gear.recipe(((FE_PLATE, 2),), GEAR, GEAR_TIME)
asm_gear.in_belt = bus
asm_gear.in_pos = BUS_GEAR_IN
asm_gear.ins_rect = (62, 68, 67, 72)
asm_gear.out_belt = bus
asm_gear.out_pos = BUS_GEAR_OUT

asm_circ.recipe(((FE_PLATE, 1), (CU_PLATE, 1)), CHIP, CHIP_TIME)
asm_circ.in_belt = bus
asm_circ.in_pos = BUS_CIRC_IN
asm_circ.ins_rect = (96, 68, 101, 72)
asm_circ.out_belt = bus
asm_circ.out_pos = BUS_CIRC_OUT

# The lab's recipe changes with the research being run; see STAGE_PLAN.
lab.in_belt = bus
lab.in_pos = BUS_LAB_IN
lab.ins_rect = (15, 80, 20, 85)
lab.ins_vertical = False
lab.out_belt = None
lab.out = -1

# Ore patches, hand-scattered to dodge the belts running through them.
ORE_FE_TILES = ((29, 2), (34, 2), (39, 2), (44, 2),
                (29, 19), (34, 19), (39, 19), (29, 23), (39, 23))
ORE_CU_TILES = ((29, 28), (34, 28), (39, 28), (44, 28),
                (29, 45), (34, 45), (39, 45), (34, 50), (44, 45))


# ==================================================================
# Hardware
# ==================================================================
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)


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
# Scene graph: factory floor on top, HUD underneath, alt-mode labels
# and a message overlay on top of both.
# ==================================================================
scene = displayio.Group()

view = displayio.Bitmap(VW, VH, PAL_LEN)
scene.append(displayio.TileGrid(view, pixel_shader=palette, x=0, y=0))

H_BG, H_FRAME, H_YELLOW, H_RED, H_GREEN = 0, 1, 2, 3, 4
hud_pal = displayio.Palette(5)
hud_pal[H_BG] = 0x0E0E12
hud_pal[H_FRAME] = 0x44444C
hud_pal[H_YELLOW] = 0xD8B23A
hud_pal[H_RED] = 0xD8404A
hud_pal[H_GREEN] = 0x56C85A

hud = displayio.Bitmap(VW, HUD_H, 5)
scene.append(displayio.TileGrid(hud, pixel_shader=hud_pal, x=0, y=VH))


def _hud_label(text, color, x, y, right=False):
    lbl = label.Label(terminalio.FONT, text=text, color=color)
    lbl.anchor_point = (1.0 if right else 0.0, 0.5)
    lbl.anchored_position = (x, y)
    scene.append(lbl)
    return lbl


goal_label = _hud_label("IRON SMELTING", 0xFFD24A, 4, VH + 9)
pwr_label = _hud_label("PWR 100%", 0x7FC6E4, VW - 4, VH + 9, right=True)
sci_label = _hud_label("", 0xB0B4BC, 4, VH + 20)
store_label = _hud_label("STORE 0", 0xB0B4BC, VW - 4, VH + 20, right=True)

# ALT-MODE: the real game labels every machine with what it makes when
# you hold Alt. One tiny label per structure, hidden as a group.
alt_group = displayio.Group()
ALT_TEXT = (
    (drill_fe, "Fe"), (furn_fe, "Fe"), (drill_cu, "Cu"), (furn_cu, "Cu"),
    (asm_gear, "GEAR"), (asm_circ, "CHIP"), (lab, "SCI"),
    (engine, "PWR"), (beacon, "MOD"),
)
alt_labels = []
for (_m, _t) in ALT_TEXT:
    _l = label.Label(terminalio.FONT, text=_t, color=0xFFFFFF)
    _l.anchor_point = (0.5, 0.5)
    _l.anchored_position = (_m.cx, _m.cy)
    alt_group.append(_l)
    alt_labels.append((_m, _l, _t))
chest_label = label.Label(terminalio.FONT, text="0", color=0xFFFFFF)
chest_label.anchor_point = (0.5, 0.5)
chest_label.anchored_position = (chest.cx, chest.cy)
alt_group.append(chest_label)
alt_group.hidden = True
scene.append(alt_group)

msg_group = displayio.Group()
msg_main = label.Label(terminalio.FONT, text="", color=0xD8B23A, scale=2)
msg_main.anchor_point = (0.5, 0.5)
msg_main.anchored_position = (VW // 2, VH // 2 - 8)
msg_group.append(msg_main)
msg_sub = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
msg_sub.anchor_point = (0.5, 0.5)
msg_sub.anchored_position = (VW // 2, VH // 2 + 14)
msg_group.append(msg_sub)
msg_group.hidden = True
scene.append(msg_group)

display.root_group = scene


# ==================================================================
# The growth plan. Each stage builds something the moment it starts,
# then waits for a goal: either a pile of material in the storage chest
# or a number of science packs out of the lab. Meeting the goal starts
# the next stage, so the factory expands the way it does in the game --
# because the last expansion finally paid off.
# ==================================================================
STAGE_PLAN = (
    {"name": "IRON SMELTING",
     "build": ("drill_fe", "furn_fe", "chest", "boiler", "engine"),
     "goal": ("store", FE_PLATE, 10), "bar": H_YELLOW, "led": (200, 170, 60)},
    {"name": "COPPER SMELTING",
     "build": ("drill_cu", "furn_cu"),
     "goal": ("store", CU_PLATE, 8), "bar": H_YELLOW, "led": (200, 120, 50)},
    {"name": "IRON GEARS",
     "build": ("asm_gear",),
     "goal": ("store", GEAR, 6), "bar": H_YELLOW, "led": (150, 155, 165)},
    {"name": "AUTOMATION",
     "build": ("lab",),
     "goal": ("science", 8), "bar": H_RED, "led": (210, 50, 60),
     "lab": (((GEAR, 1), (CU_PLATE, 1)), 2.0)},
    {"name": "ELECTRONICS",
     "build": ("asm_circ",),
     "goal": ("science", 10), "bar": H_GREEN, "led": (60, 200, 80),
     "lab": (((GEAR, 1), (CHIP, 1)), 2.0)},
    {"name": "SPEED MODULES",
     "build": ("beacon",),
     "goal": ("science", 12), "bar": H_GREEN, "led": (60, 200, 80),
     "lab": (((GEAR, 1), (CHIP, 1)), 1.8)},
)

# Building the beacon slots speed modules into everything nearby: the
# factory visibly winds up -- and pulls more power than the one steam
# engine can supply, which is also exactly what happens in the game.
MODULE_MACHINE_SPEED = 1.4
MODULE_BELT_SPEED = 1.3


# ==================================================================
# Static renderer -- floor, ore, and machine shells. Repainted only
# when a structure appears, which is a handful of times per run.
# ==================================================================
def draw_ghost(m):
    """An unbuilt machine shows as a blueprint outline, so the shape of
    the finished factory is visible from the first second."""
    fill_region(view, m.x0, m.y0, m.x1, m.y1, GHOST_FILL)
    fill_region(view, m.x0, m.y0, m.x1, m.y0 + 1, GHOST_LINE)
    fill_region(view, m.x0, m.y1 - 1, m.x1, m.y1, GHOST_LINE)
    fill_region(view, m.x0, m.y0, m.x0 + 1, m.y1, GHOST_LINE)
    fill_region(view, m.x1 - 1, m.y0, m.x1, m.y1, GHOST_LINE)


def draw_shell(m):
    """The parts of a built machine that never move."""
    x0, y0, x1, y1 = m.x0, m.y0, m.x1, m.y1
    k = m.kind

    if k == "drill":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, METAL)
        fill_region(view, x0 + 2, y0 + 2, x1 - 2, y0 + 5, YELLOW)
        fill_region(view, x0 + 2, y1 - 5, x1 - 2, y1 - 2, YELLOW)
        fill_region(view, x0 + 4, y0 + 7, x1 - 4, y1 - 7, SHADOW)   # the pit
        fill_region(view, x1 - 4, m.cy - 2, x1, m.cy + 3, METAL_L)  # ore chute

    elif k == "furnace":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, METAL)
        fill_region(view, x0 + 4, y0 + 2, x0 + 8, y0 + 5, SHADOW)   # vents
        fill_region(view, x1 - 8, y0 + 2, x1 - 4, y0 + 5, SHADOW)
        fill_region(view, x0 + 3, y0 + 7, x1 - 3, y1 - 3, METAL_D)  # firebox wall
        fill_region(view, x1 - 3, m.cy - 2, x1, m.cy + 3, METAL_L)  # plate chute

    elif k == "asm":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, ASM_BODY)
        for (bx, by) in ((x0 + 2, y0 + 2), (x1 - 4, y0 + 2),
                         (x0 + 2, y1 - 4), (x1 - 4, y1 - 4)):
            fill_region(view, bx, by, bx + 2, by + 2, YELLOW)

    elif k == "lab":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, LAB_BODY)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y0 + 5, METAL)    # roof
        fill_region(view, x0 + 3, y1 - 4, x1 - 3, y1 - 1, METAL_D)  # bench
        for bx in (x0 + 6, x0 + 13, x0 + 20):                       # beaker glass
            fill_region(view, bx, y0 + 8, bx + 5, y1 - 4, METAL_D)

    elif k == "chest":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, METAL)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y0 + 4, METAL_L)  # lid
        fill_region(view, x0 + 1, y0 + 6, x1 - 1, y0 + 7, METAL_D)

    elif k == "boiler":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, BRICK)
        fill_region(view, x0 + 2, y0 + 2, x1 - 2, y0 + 4, METAL_D)  # flue

    elif k == "engine":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, METAL)
        fill_region(view, x0 + 1, y1 - 4, x1 - 1, y1 - 1, METAL_D)  # bedplate

    elif k == "beacon":
        fill_region(view, x0, y0, x1, y1, METAL_D)
        fill_region(view, x0 + 1, y0 + 1, x1 - 1, y1 - 1, ASM_BODY)
        fill_region(view, x0 + 3, y0 + 3, x1 - 3, y1 - 3, SHADOW)


def draw_static():
    fill_region(view, 0, 0, VW, VH, FLOOR)
    for gy in range(0, VH, 8):
        fill_region(view, 0, gy, VW, gy + 1, FLOOR_LINE)

    # A hazard-striped walkway across the empty floor south of the
    # assemblers -- concrete this bare reads as unfinished otherwise.
    for wx in range(20, 92, 8):
        fill_region(view, wx, 96, wx + 4, 99, YELLOW)
        fill_region(view, wx + 4, 96, wx + 8, 99, SHADOW)

    for (ox, oy) in ORE_FE_TILES:
        fill_region(view, ox, oy, ox + 4, oy + 4, ORE_FE)
    for (ox, oy) in ORE_CU_TILES:
        fill_region(view, ox, oy, ox + 4, oy + 4, ORE_CU)

    for m in STRUCTURES:
        if m.built:
            draw_shell(m)
        else:
            draw_ghost(m)

    # Steam pipe, only once there is something at both ends of it.
    if boiler.built and engine.built:
        fill_region(view, boiler.x1, boiler.cy - 2, engine.x0,
                    boiler.cy + 2, METAL_L)


# ==================================================================
# Per-frame renderer
# ==================================================================
def draw_belt(b, phase):
    """Lane, then the corner patches that square off the turns, then the
    moving chevrons. Three passes so nothing paints over a turn."""
    for (_base, x0, y0, ux, uy, ln) in b.segs:
        x1 = x0 + ux * ln
        y1 = y0 + uy * ln
        if uy == 0.0:
            ax = int(min(x0, x1))
            bx = int(max(x0, x1))
            fill_region(view, ax, y0 - BELT_HALF, bx, y0 + BELT_HALF + 1,
                        BELT_FRAME)
            fill_region(view, ax, y0 - LANE_HALF, bx, y0 + LANE_HALF + 1,
                        BELT_LANE)
        else:
            ay = int(min(y0, y1))
            by = int(max(y0, y1))
            fill_region(view, x0 - BELT_HALF, ay, x0 + BELT_HALF + 1, by,
                        BELT_FRAME)
            fill_region(view, x0 - LANE_HALF, ay, x0 + LANE_HALF + 1, by,
                        BELT_LANE)

    for i in range(1, len(b.points) - 1):
        wx, wy = b.points[i]
        fill_region(view, wx - BELT_HALF, wy - BELT_HALF,
                    wx + BELT_HALF + 1, wy + BELT_HALF + 1, BELT_FRAME)
        fill_region(view, wx - LANE_HALF, wy - LANE_HALF,
                    wx + LANE_HALF + 1, wy + LANE_HALF + 1, BELT_LANE)

    for (_base, x0, y0, ux, uy, ln) in b.segs:
        d = TREAD_PITCH - (phase % TREAD_PITCH)
        while d < ln:
            if uy == 0.0:
                px = int(x0 + ux * d)
                fill_region(view, px, y0 - LANE_HALF, px + 2,
                            y0 + LANE_HALF + 1, BELT_TREAD)
            else:
                py = int(y0 + uy * d)
                fill_region(view, x0 - LANE_HALF, py, x0 + LANE_HALF + 1,
                            py + 2, BELT_TREAD)
            d += TREAD_PITCH


def draw_items(b):
    half = ITEM_SIZE >> 1
    for (pos, kind) in b.items:
        px, py = b.point_at(pos)
        ix = int(px) - half
        iy = int(py) - half
        if ix < 0:
            ix = 0
        if iy < 0:
            iy = 0
        if ix + ITEM_SIZE > VW:
            ix = VW - ITEM_SIZE
        if iy + ITEM_SIZE > VH:
            iy = VH - ITEM_SIZE
        fill_region(view, ix, iy, ix + ITEM_SIZE, iy + ITEM_SIZE,
                    ITEM_COLOR[kind])
        # One extra pixel of detail is enough to tell the two crafted
        # items apart at this size: gears have a hole, chips have a trace.
        if kind == GEAR:
            fill_region(view, ix + 2, iy + 2, ix + 3, iy + 3, SHADOW)
        elif kind == CHIP:
            fill_region(view, ix + 1, iy + 2, ix + 4, iy + 3, SHADOW)


def draw_anim(m, t):
    """Repaint the one small panel inside a machine that moves."""
    if not m.built:
        return
    x0, y0, x1, y1 = m.x0, m.y0, m.x1, m.y1
    k = m.kind

    if k == "drill":
        # The head sweeps across the pit while it is mining, and parks
        # when the output belt is full -- a stalled drill looks stalled.
        px0 = x0 + 4
        px1 = x1 - 4
        fill_region(view, px0, y0 + 7, px1, y1 - 7, SHADOW)
        span = px1 - px0 - 4
        if m.blocked:
            hx = px0 + (span >> 1)
        else:
            hx = px0 + int(span * abs(1.0 - 2.0 * m.progress))
        fill_region(view, hx, y0 + 7, hx + 4, y1 - 7,
                    ORE_FE if m is drill_fe else ORE_CU)

    elif k == "furnace":
        # Firebox glow, brightest just as the plate pops out.
        fill_region(view, x0 + 3, y0 + 7, x1 - 3, y1 - 3, METAL_D)
        if m.crafting:
            hot = FIRE if (m.progress > 0.6 or random.random() < 0.3) else ORANGE
            h = 3 + int((y1 - y0 - 14) * m.progress)
            fill_region(view, x0 + 5, y1 - 3 - h, x1 - 5, y1 - 3, hot)

    elif k == "asm":
        # Window flickers while assembling, plus a progress bar.
        fill_region(view, x0 + 6, y0 + 5, x1 - 6, y1 - 8,
                    GLASS_HOT if m.crafting else GLASS)
        fill_region(view, x0 + 4, y1 - 6, x1 - 4, y1 - 3, SHADOW)
        w = int((x1 - x0 - 8) * m.progress)
        if w > 0:
            fill_region(view, x0 + 4, y1 - 6, x0 + 4 + w, y1 - 3, YELLOW)

    elif k == "lab":
        # Three beakers filling up with the current science pack.
        col = SCI_RED if lab_bar == H_RED else SCI_GRN
        for i, bx in enumerate((x0 + 6, x0 + 13, x0 + 20)):
            fill_region(view, bx, y0 + 8, bx + 5, y1 - 4, METAL_D)
            # Stagger the three so they read as bubbling, not as one bar.
            f = m.progress + i * 0.33
            if f > 1.0:
                f -= 1.0
            h = int((y1 - 4 - (y0 + 8)) * f)
            if h > 0:
                fill_region(view, bx + 1, y1 - 4 - h, bx + 4, y1 - 4, col)

    elif k == "chest":
        # Three slots previewing what is piling up inside.
        fill_region(view, x0 + 3, y0 + 9, x1 - 3, y1 - 3, SHADOW)
        slot = 0
        for kind in range(N_ITEMS):
            if store[kind] and slot < 3:
                sx = x0 + 4 + slot * 6
                fill_region(view, sx, y0 + 10, sx + 5, y0 + 15,
                            ITEM_COLOR[kind])
                slot += 1

    elif k == "boiler":
        flick = FIRE if random.random() < 0.5 else ORANGE
        fill_region(view, x0 + 3, y1 - 7, x1 - 3, y1 - 3, flick)

    elif k == "engine":
        # Flywheel: a crank pin walking a little square orbit, and a
        # piston rod sliding in and out with it.
        fill_region(view, x0 + 1, y0 + 5, x1 - 1, y1 - 5, METAL)
        step = int(t * 9.0) % 4
        ox, oy = ((3, 0), (5, 2), (3, 4), (1, 2))[step]
        fill_region(view, x1 - 8 + ox - 1, y0 + 5 + oy, x1 - 8 + ox + 2,
                    y0 + 8 + oy, SHADOW)
        rod = 2 + (ox >> 1)
        fill_region(view, x0 + 2, m.cy - 1, x0 + 2 + rod + 3, m.cy + 2,
                    METAL_L)

    elif k == "beacon":
        pulse = 0.5 + 0.5 * math.sin(t * 5.0)
        fill_region(view, x0 + 3, y0 + 3, x1 - 3, y1 - 3, SHADOW)
        w = int((x1 - x0 - 10) * pulse)
        if w > 0:
            fill_region(view, m.cx - (w >> 1) - 1, y0 + 5,
                        m.cx + (w >> 1) + 1, y1 - 5, BEACON_C)
        if pulse > 0.7:
            for (bx, by) in ((x0 + 1, y0 + 1), (x1 - 3, y0 + 1),
                             (x0 + 1, y1 - 3), (x1 - 3, y1 - 3)):
                fill_region(view, bx, by, bx + 2, by + 2, YELLOW)


def draw_inserter(m):
    """The arm swings from the belt to the machine, carrying its item."""
    if not m.built or m.ins_rect is None:
        return
    cx0, cy0, cx1, cy1 = m.ins_rect
    fill_region(view, cx0, cy0, cx1, cy1, FLOOR)
    if m.arm_item >= 0:
        t = 1.0 - m.arm_cool / INSERTER_TIME
        carry = ITEM_COLOR[m.arm_item]
    else:
        t = 1.0
        carry = -1
    if m.ins_vertical:
        span = cy1 - cy0 - 3
        ay = cy0 + int(span * t)
        fill_region(view, cx0 + 1, ay, cx1 - 1, ay + 3, METAL_L)
        if carry >= 0:
            fill_region(view, cx0 + 1, ay, cx1 - 1, ay + 2, carry)
    else:
        span = cx1 - cx0 - 3
        ax = cx1 - 3 - int(span * t)
        fill_region(view, ax, cy0 + 1, ax + 3, cy1 - 1, METAL_L)
        if carry >= 0:
            fill_region(view, ax, cy0 + 1, ax + 2, cy1 - 1, carry)


# ==================================================================
# HUD + LEDs
# ==================================================================
def draw_hud_chrome():
    fill_region(hud, 0, 0, VW, HUD_H, H_BG)
    fill_region(hud, 0, 0, VW, 2, H_FRAME)          # separator under the floor
    fill_region(hud, 4, 27, VW - 4, 37, H_FRAME)    # progress bar frame


def update_hud(frac, bar_color):
    goal_label.text = toast if toast else STAGE_PLAN[stage]["name"]
    goal_label.color = 0xFFFFFF if toast else 0xFFD24A

    pct = int(power_ratio * 100.0)
    pwr_label.text = "PWR %d%%" % pct
    pwr_label.color = 0x7FC6E4 if pct >= 100 else 0xE8721C

    goal = STAGE_PLAN[stage]["goal"]
    if goal[0] == "science":
        sci_label.text = "SCI %d/%d" % (lab.count, goal[1])
    else:
        sci_label.text = "NEED %d %s" % (goal[2], ITEM_LABEL[goal[1]])

    total = 0
    for i in range(N_ITEMS):
        total += store[i]
    store_label.text = "STORE %d" % total
    chest_label.text = "%d" % total

    fill_region(hud, 6, 29, VW - 6, 35, H_BG)
    if frac > 1.0:
        frac = 1.0
    w = int((VW - 12) * frac)
    if w > 0:
        fill_region(hud, 6, 29, 6 + w, 35, bar_color)


ITEM_LABEL = ("ORE", "ORE", "PLATE", "COPPER", "GEARS", "CHIPS")


def update_leds(frac, rgb, flash):
    """5 pixels = progress toward the current goal; `flash` wins for a frame."""
    if flash == "build":
        for i in range(5):
            pixels[i] = (60, 190, 220)
        pixels.show()
        return
    if flash == "craft":
        for i in range(5):
            pixels[i] = (255, 235, 180)
        pixels.show()
        return
    lit = frac * 5.0
    brown = power_ratio < 0.99
    for i in range(5):
        level = lit - i
        if level <= 0.0:
            pixels[i] = (12, 6, 0) if brown else (0, 0, 0)
        else:
            if level > 1.0:
                level = 1.0
            pixels[i] = (int(rgb[0] * level), int(rgb[1] * level),
                         int(rgb[2] * level))
    pixels.show()


def show_message(main, sub, color):
    msg_main.text = main
    msg_main.color = color
    msg_sub.text = sub
    msg_group.hidden = False


# ==================================================================
# Factory state
# ==================================================================
store = bytearray(N_ITEMS)      # everything that reached the storage chest
stage = 0
lab_bar = H_YELLOW
machine_speed = 1.0
belt_mult = 1.0
power_demand = 0
power_ratio = 1.0
toast = ""
toast_until = 0.0
static_dirty = True


def recompute_power():
    global power_demand, power_ratio
    power_demand = 0
    for m in STRUCTURES:
        if m.built:
            power_demand += m.power
    if power_demand <= POWER_SUPPLY:
        power_ratio = 1.0
    else:
        power_ratio = POWER_SUPPLY / float(power_demand)


def set_toast(text, now):
    global toast, toast_until
    toast = text
    toast_until = now + 1.8


def start_stage(idx, now):
    """Build whatever this stage unlocks and point the lab at its research."""
    global stage, lab_bar, machine_speed, belt_mult, static_dirty
    stage = idx
    plan = STAGE_PLAN[idx]
    for name in plan["build"]:
        m = BY_NAME[name]
        if not m.built:
            m.built = True
            print("Factorio: built %s" % name)
    if "lab" in plan:
        inputs, craft_time = plan["lab"]
        lab.recipe(inputs, -1, craft_time)
        lab.count = 0
    lab_bar = plan["bar"]
    if beacon.built:
        machine_speed = MODULE_MACHINE_SPEED
        belt_mult = MODULE_BELT_SPEED
    recompute_power()
    static_dirty = True
    set_toast(plan["name"], now)
    print("Factorio: stage %d -- %s" % (idx, plan["name"]))


def reset_factory(now):
    global store, stage, machine_speed, belt_mult, static_dirty
    for b in BELTS:
        b.clear()
    for m in STRUCTURES:
        m.reset()
    store = bytearray(N_ITEMS)
    machine_speed = 1.0
    belt_mult = 1.0
    msg_group.hidden = True
    static_dirty = True
    start_stage(0, now)


def stage_progress():
    goal = STAGE_PLAN[stage]["goal"]
    if goal[0] == "store":
        need = goal[2]
        return store[goal[1]] / float(need), STAGE_PLAN[stage]["bar"]
    need = goal[1]
    return lab.count / float(need), STAGE_PLAN[stage]["bar"]


def goal_met():
    goal = STAGE_PLAN[stage]["goal"]
    if goal[0] == "store":
        return store[goal[1]] >= goal[2]
    return lab.count >= goal[1]


# ==================================================================
# One simulation step
# ==================================================================
def step(dt):
    """Advance belts and machines. Returns an LED flash hint or None."""
    flash = None

    dist = BELT_SPEED * belt_mult * dt
    for b in BELTS:
        b.advance(dist)

    # Belt-to-belt handoff: the copper feeder tips onto the main bus.
    k = belt_cu_plate.front_at_end()
    if k >= 0 and bus.try_insert(BUS_CU_MERGE, k):
        belt_cu_plate.take_end()

    # Anything that survives the whole bus is stored -- the chest is a
    # bottomless sink on purpose. A permanently jammed bus would leave
    # the badge showing a frozen factory forever.
    k = bus.front_at_end()
    if k >= 0 and chest.built:
        bus.take_end()
        if store[k] < 255:
            store[k] += 1

    mdt = dt * machine_speed * power_ratio
    for m in STRUCTURES:
        if m.tick(mdt):
            flash = "craft" if m is lab else flash
    return flash


# ==================================================================
# One factory, from first drill to last research. Returns True when the
# plan is finished, False if SW3 asked for a fresh one.
# ==================================================================
def run_factory():
    global static_dirty, toast, alt_mode

    # Same courtesy the launcher extends: wait for a finger to come off
    # the switches before reading fresh presses, or one long press on
    # SW3 rebuilds the factory over and over instead of once.
    while not (sw1.value and sw2.value and sw3.value):
        time.sleep(0.02)

    now = time.monotonic()
    reset_factory(now)

    last = now
    phase = 0.0
    hud_at = 0.0
    led_flash = None
    sw1_prev = sw2_prev = sw3_prev = True

    while True:
        now = time.monotonic()
        dt = now - last
        last = now
        if dt > 0.15:            # a GC hitch must not teleport an item
            dt = 0.15
        elif dt < 0.0:
            dt = 0.0

        # ---- buttons ------------------------------------------------
        v1, v2, v3 = sw1.value, sw2.value, sw3.value
        if (not v1) and sw1_prev:
            alt_mode = not alt_mode
            alt_group.hidden = not alt_mode
        if (not v3) and sw3_prev:
            print("Factorio: rebuilding")
            return False
        sw1_prev, sw2_prev, sw3_prev = v1, v2, v3
        warp = 3.0 if not v2 else 1.0

        sdt = dt * warp
        phase += BELT_SPEED * belt_mult * sdt
        flash = step(sdt)
        if flash:
            led_flash = flash

        if toast and now >= toast_until:
            toast = ""

        if goal_met():
            if stage + 1 >= len(STAGE_PLAN):
                return True
            start_stage(stage + 1, now)
            led_flash = "build"

        # ---- render -------------------------------------------------
        if static_dirty:
            draw_static()
            static_dirty = False
        for b in BELTS:
            draw_belt(b, phase)
        for b in BELTS:
            draw_items(b)
        for m in STRUCTURES:
            draw_anim(m, now)
        draw_inserter(asm_gear)
        draw_inserter(asm_circ)
        draw_inserter(lab)
        display.refresh()

        frac, bar = stage_progress()
        if now - hud_at >= 0.25 or led_flash:
            hud_at = now
            update_hud(frac, bar)
        update_leds(frac, STAGE_PLAN[stage]["led"], led_flash)
        led_flash = None


# ==================================================================
# Boot: title card, then grow factories forever.
# ==================================================================
try:                             # vary the furnace flicker across boots
    random.seed(time.monotonic_ns())
except AttributeError:
    pass

alt_mode = False
draw_hud_chrome()
fill_region(view, 0, 0, VW, VH, FLOOR)
show_message("FACTORIO", "the factory must grow", 0xD8B23A)
update_hud(0.0, H_YELLOW)
display.refresh()
bl.value = True
update_leds(0.0, (200, 170, 60), None)
time.sleep(2.0)

run_num = 0
while True:
    run_num += 1
    print("Factorio: factory %d starting" % run_num)
    finished = run_factory()
    if not finished:
        continue

    print("Factorio: factory %d complete" % run_num)
    show_message("COMPLETE", "it must grow", 0x56C85A)
    display.refresh()
    for pulse in range(24):      # a short victory ripple down the strip
        for i in range(5):
            pixels[i] = (0, 200, 80) if (pulse + i) % 5 < 2 else (0, 30, 12)
        pixels.show()
        time.sleep(0.12)
