"""
code.py -- "DOOM" autoplay demo for the Carolina Code Conference 2026 badge.
===========================================================================
A from-scratch raycasting first-person shooter that plays itself: textured-ish
walls, billboarded monsters that hunt you, hitscan combat, a bobbing weapon,
a HUD, and the NeoPixel strip as a health bar.

Nobody touches the badge. A bot drives the marine -- it paths around the
level with breadth-first search, hunts monsters, restocks ammo when it runs
low, and shoots what it can see. When it wins or dies the level resets and
the demo starts over, so the badge can sit on a table running forever.

This is NOT id Software's DOOM -- see README.md for why the real thing
cannot run on this hardware. This is the badge's own take on the idea.

Controls
--------
None. It is a demo -- the buttons are deliberately left alone so the
launcher can keep them. See README.md for the one-function change that
turns the bot back into a human player.

Rendering
---------
Everything is drawn into one 128x112 indexed `displayio.Bitmap` using
`bitmaptools.fill_region`, which fills a rectangle in C. Nothing is
plotted pixel-by-pixel from Python -- that is the entire performance
trick. A frame is roughly:

    12 fills   sky + floor gradient bands (full width)
    64 fills   one vertical wall strip per ray
   ~50 fills   monster sprites, clipped against the depth buffer
   ~36 fills   the weapon

STRIP_W below is the quality/speed knob: 2 (default) casts 64 rays,
4 casts 32 and roughly halves the raycasting cost.
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

# `bitmaptools` is a built-in module on the ESP32-S3 CircuitPython
# build. The pure-Python fallback keeps the demo running (very slowly)
# on a build without it rather than crashing on import.
try:
    from bitmaptools import fill_region
except ImportError:
    def fill_region(bmp, x1, y1, x2, y2, value):
        for _y in range(y1, y2):
            for _x in range(x1, x2):
                bmp[_x, _y] = value


# ==================================================================
# Screen layout -- the display is 128 wide x 160 tall (portrait).
# The top 112 rows are the 3D view, the bottom 48 are the HUD.
# ==================================================================
VW = 128            # viewport width
VH = 112            # viewport height
HUD_H = 160 - VH
HORIZON = VH // 2

STRIP_W = 2                     # pixels per ray -- see module docstring
NUM_STRIPS = VW // STRIP_W

FOV_PLANE = 0.66                # camera plane length ~= 66 degree FOV


# ==================================================================
# The level. '.' is open floor, anything else is a wall whose
# character picks the wall colour. 16x16, walled all the way round.
#
# Deliberately open-plan: the monsters walk straight at whatever they
# are chasing, so tight mazes leave them wedged in corners. Free-
# standing pillars give cover without creating dead ends, and the one
# enclosed room in the middle has a wide south entrance.
# ==================================================================
MAP = (
    "################",
    "#..............#",
    "#..==....==....#",
    "#..==....==....#",
    "#..............#",
    "#....++++++....#",
    "#....+....+....#",
    "#....+....+....#",
    "#..............#",
    "#..==....==....#",
    "#..==....==....#",
    "#..............#",
    "#....%%..%%....#",
    "#....%%..%%....#",
    "#..............#",
    "################",
)
MW = len(MAP[0])
MH = len(MAP)

WALL_CHARS = "#=+%"              # index into WALL_BASE_COLORS

# Flatten the map into one bytearray -- indexing a bytearray is much
# cheaper in the DDA inner loop than indexing a tuple of strings.
# Value 0 = open, 1..4 = wall type + 1.
GRID = bytearray(MW * MH)
for _y in range(MH):
    _row = MAP[_y]
    for _x in range(MW):
        _c = _row[_x]
        GRID[_y * MW + _x] = 0 if _c == "." else WALL_CHARS.index(_c) + 1


# ==================================================================
# Palette. The viewport bitmap stores palette indices, so every
# colour the renderer can draw has to be allocated up front.
# ==================================================================
CEIL_0 = 0                       # 6 sky bands,   indices 0..5
FLOOR_0 = 6                      # 6 floor bands, indices 6..11
WALL_0 = 12                      # 4 wall types x 4 shades, 12..27
ENEMY_0 = 28                     # 28..31
GUN_0 = 32                       # 32..35
CROSSHAIR = 36
PICKUP_0 = 37                    # 37..38
PAL_LEN = 40

WALL_BASE_COLORS = (0x9096A0, 0xA85830, 0x2E8B57, 0xB03038)
WALL_SHADES = (1.0, 0.70, 0.48, 0.32)


def _shade(color, f):
    r = int(((color >> 16) & 0xFF) * f)
    g = int(((color >> 8) & 0xFF) * f)
    b = int((color & 0xFF) * f)
    return (r << 16) | (g << 8) | b


def _lerp(c0, c1, t):
    r = int(((c0 >> 16) & 0xFF) + (((c1 >> 16) & 0xFF) - ((c0 >> 16) & 0xFF)) * t)
    g = int(((c0 >> 8) & 0xFF) + (((c1 >> 8) & 0xFF) - ((c0 >> 8) & 0xFF)) * t)
    b = int((c0 & 0xFF) + ((c1 & 0xFF) - (c0 & 0xFF)) * t)
    return (r << 16) | (g << 8) | b


palette = displayio.Palette(PAL_LEN)

# Sky: lighter overhead (close) fading to dark at the horizon (far).
for i in range(6):
    palette[CEIL_0 + i] = _lerp(0x2C3040, 0x0C0E16, i / 5.0)
# Floor: dark at the horizon, warmer and brighter underfoot.
for i in range(6):
    palette[FLOOR_0 + i] = _lerp(0x181008, 0x53381F, i / 5.0)
# Walls: 4 types x 4 distance shades.
for t in range(4):
    for s in range(4):
        palette[WALL_0 + t * 4 + s] = _shade(WALL_BASE_COLORS[t], WALL_SHADES[s])

palette[ENEMY_0 + 0] = 0x8E3B22   # 'a' hide
palette[ENEMY_0 + 1] = 0x4A1B0E   # 'b' shadow
palette[ENEMY_0 + 2] = 0xFFD21E   # 'c' eyes
palette[ENEMY_0 + 3] = 0xD8CBB0   # 'd' horns / claws
palette[GUN_0 + 0] = 0x585C64     # 'g' body
palette[GUN_0 + 1] = 0x8E949E     # 'h' highlight
palette[GUN_0 + 2] = 0x24262A     # 'i' shadow
palette[GUN_0 + 3] = 0xFFE68A     # 'f' muzzle flash
palette[CROSSHAIR] = 0x30FF60
palette[PICKUP_0 + 0] = 0x4C5A28  # 'm' ammo box shell
palette[PICKUP_0 + 1] = 0xE0A82C  # 'n' brass


# ==================================================================
# Sprite art. '.' is transparent; other letters index the palette
# through the maps below. Runs of identical vertical pixels are
# pre-merged per column so each run costs exactly one fill_region.
# ==================================================================
ENEMY_ART = (
    "....aaaa....",
    "...aaaaaa...",
    "..daaaaaad..",
    "..daaaaaad..",
    "..acaaaaca..",
    "..aaaaaaaa..",
    "...abbba....",
    "..aaaaaaaa..",
    ".baaaaaaaab.",
    ".baaaaaaaab.",
    ".baaaaaaaab.",
    "..aaaaaaaa..",
    "..aaa..aaa..",
    "..bbb..bbb..",
    "..bb....bb..",
    "..dd....dd..",
)
ENEMY_COLORS = {"a": ENEMY_0, "b": ENEMY_0 + 1, "c": ENEMY_0 + 2, "d": ENEMY_0 + 3}

GUN_ART = (
    "......ffff......",
    ".....ffffff.....",
    "......iggi......",
    "......ighi......",
    "......ighi......",
    ".....iigghii....",
    "....iiggghhii...",
    "...iigggghhhii..",
    "..iiggggghhhhii.",
    "..iiggggghhhhii.",
)
GUN_COLORS = {"g": GUN_0, "h": GUN_0 + 1, "i": GUN_0 + 2, "f": GUN_0 + 3}

AMMO_ART = (
    "..mmmm..",
    ".mnnnnm.",
    ".mnnnnm.",
    ".mmmmmm.",
    "..mmmm..",
)
AMMO_COLORS = {"m": PICKUP_0, "n": PICKUP_0 + 1}


def build_columns(art, colors):
    """Turn ASCII art into per-column (y0, y1, palette_index) runs."""
    h = len(art)
    w = len(art[0])
    cols = []
    for x in range(w):
        runs = []
        y = 0
        while y < h:
            c = art[y][x]
            if c == ".":
                y += 1
                continue
            y2 = y + 1
            while y2 < h and art[y2][x] == c:
                y2 += 1
            runs.append((y, y2, colors[c]))
            y = y2
        cols.append(tuple(runs))
    return tuple(cols), w, h


ENEMY_COLS, ENEMY_W, ENEMY_H = build_columns(ENEMY_ART, ENEMY_COLORS)
GUN_COLS, GUN_W, GUN_H = build_columns(GUN_ART, GUN_COLORS)
AMMO_COLS, AMMO_W, AMMO_H = build_columns(AMMO_ART, AMMO_COLORS)

# A copy of the monster columns with every run recoloured to the
# muzzle-flash cream, used for the one-frame hit flash.
ENEMY_HURT_COLS = tuple(
    tuple((a, b, GUN_0 + 3) for (a, b, _c) in col) for col in ENEMY_COLS
)
# ...and a copy of the weapon without its two flash rows, for the
# overwhelming majority of frames where nothing is being fired.
GUN_NOFLASH_COLS = tuple(
    tuple(run for run in col if run[2] != GUN_0 + 3) for col in GUN_COLS
)

GUN_SCALE = 4
GUN_PIX_W = GUN_W * GUN_SCALE
GUN_PIX_H = GUN_H * GUN_SCALE
GUN_X0 = (VW - GUN_PIX_W) // 2


# ==================================================================
# Hardware. The three tactile switches are intentionally not claimed
# -- this demo takes no input, so there is no reason to hold them.
# ==================================================================
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)

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
# Scene graph: 3D viewport on top, HUD underneath, message overlay.
# ==================================================================
scene = displayio.Group()

view = displayio.Bitmap(VW, VH, PAL_LEN)
scene.append(displayio.TileGrid(view, pixel_shader=palette, x=0, y=0))

hud_pal = displayio.Palette(5)
hud_pal[0] = 0x101014        # background
hud_pal[1] = 0x503018        # separator / bar frame
hud_pal[2] = 0x30C040        # health, healthy
hud_pal[3] = 0xD0C020        # health, hurt
hud_pal[4] = 0xD02020        # health, critical

hud = displayio.Bitmap(VW, HUD_H, 5)
scene.append(displayio.TileGrid(hud, pixel_shader=hud_pal, x=0, y=VH))

hp_label = label.Label(terminalio.FONT, text="HP 100", color=0x40FF60)
hp_label.anchor_point = (0.0, 0.5)
hp_label.anchored_position = (5, VH + 12)
scene.append(hp_label)

ammo_label = label.Label(terminalio.FONT, text="AMMO 40", color=0xFFC020)
ammo_label.anchor_point = (1.0, 0.5)
ammo_label.anchored_position = (VW - 5, VH + 12)
scene.append(ammo_label)

imps_label = label.Label(terminalio.FONT, text="IMPS 6", color=0xFF6060)
imps_label.anchor_point = (0.0, 0.5)
imps_label.anchored_position = (5, VH + 26)
scene.append(imps_label)

fps_label = label.Label(terminalio.FONT, text="", color=0x606070)
fps_label.anchor_point = (1.0, 0.5)
fps_label.anchored_position = (VW - 5, VH + 26)
scene.append(fps_label)

msg_group = displayio.Group()
msg_main = label.Label(terminalio.FONT, text="", color=0xFF3020, scale=2)
msg_main.anchor_point = (0.5, 0.5)
msg_main.anchored_position = (VW // 2, HORIZON - 8)
msg_group.append(msg_main)
msg_sub = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
msg_sub.anchor_point = (0.5, 0.5)
msg_sub.anchored_position = (VW // 2, HORIZON + 16)
msg_group.append(msg_sub)
msg_group.hidden = True
scene.append(msg_group)

display.root_group = scene


def draw_hud_chrome():
    fill_region(hud, 0, 0, VW, HUD_H, 0)
    fill_region(hud, 0, 0, VW, 2, 1)                 # separator under the view
    fill_region(hud, 4, 34, VW - 4, 44, 1)           # health bar frame


draw_hud_chrome()


# ==================================================================
# Tunables
# ==================================================================
MOVE_SPEED = 2.3        # cells / second
TURN_SPEED = 2.6        # radians / second
PLAYER_RADIUS = 0.22    # keeps the camera out of walls

FIRE_COOLDOWN = 0.32
SHOT_DAMAGE = 34
SHOT_SPREAD = 0.20      # half-width, in camera-plane units, of the hit cone
SHOT_RANGE = 14.0

ENEMY_HP = 60
ENEMY_SPEED = 1.15
ENEMY_SIGHT = 9.0
ENEMY_REACH = 0.95
ENEMY_DAMAGE = 9
ENEMY_ATTACK_COOLDOWN = 1.1
ENEMY_SIDLE_S = 0.55    # how long a stuck monster sidles along a wall

START_HEALTH = 100
START_AMMO = 40
MAX_AMMO = 60
PICKUP_AMMO = 12
PICKUP_RADIUS = 0.55
PICKUP_RESPAWN_S = 11.0

# Every round draws its monsters and its starting corner fresh. The demo
# loops forever on a table, and a fixed layout replays the identical
# 20 seconds every time -- the randomisation is what makes it watchable.
ENEMY_COUNT = 7
SPAWN_MIN_RANGE = 3.5           # keep the first monster out of your face

SPAWN_POOL = (
    (13.5, 2.5), (7.5, 2.5), (2.5, 9.5), (12.5, 7.5),
    (13.5, 12.5), (7.5, 14.5), (2.5, 4.5), (14.5, 8.5),
    (4.5, 12.5), (10.5, 11.5), (1.5, 1.5), (8.5, 8.5),
)
START_POOL = ((2.5, 1.5), (13.5, 14.5), (1.5, 12.5), (14.5, 4.5), (8.5, 4.5))

# Ammo boxes respawn on a timer. Without them the bot can miss enough
# shots to end up unable to win AND unable to die -- the demo would sit
# there forever with nothing left to do.
AMMO_SPOTS = ((7.5, 6.5), (2.5, 14.5), (14.5, 1.5), (1.5, 7.5))

# Enemy record layout (plain lists -- cheaper than objects here).
E_X, E_Y, E_HP, E_COOL, E_HURT, E_SIDLE, E_SDIR = 0, 1, 2, 3, 4, 5, 6


def shuffled(seq):
    """Fisher-Yates. CircuitPython's random has no guaranteed shuffle()."""
    out = list(seq)
    for i in range(len(out) - 1, 0, -1):
        j = random.randrange(i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def roll_layout():
    """Pick a start corner and a fresh set of monster positions."""
    start_x, start_y = START_POOL[random.randrange(len(START_POOL))]
    angle = random.uniform(0.0, 6.283185)

    picks = []
    for (sx, sy) in shuffled(SPAWN_POOL):
        dx = sx - start_x
        dy = sy - start_y
        if dx * dx + dy * dy < SPAWN_MIN_RANGE * SPAWN_MIN_RANGE:
            continue
        # Jitter inside the cell so the monsters don't line up on a grid.
        picks.append((sx + random.uniform(-0.25, 0.25),
                      sy + random.uniform(-0.25, 0.25)))
        if len(picks) == ENEMY_COUNT:
            break
    return start_x, start_y, angle, picks


def is_wall(x, y):
    ix = int(x)
    iy = int(y)
    if ix < 0 or iy < 0 or ix >= MW or iy >= MH:
        return True
    return GRID[iy * MW + ix] != 0


def blocked(x, y, r):
    """True if a circle of radius r at (x, y) overlaps a wall cell."""
    return (is_wall(x - r, y - r) or is_wall(x + r, y - r) or
            is_wall(x - r, y + r) or is_wall(x + r, y + r))


# ==================================================================
# Renderer
# ==================================================================
zbuf = [1e9] * NUM_STRIPS


def draw_bands():
    """Sky and floor gradients, six full-width bands each."""
    step = HORIZON // 6
    y = 0
    for i in range(6):
        y2 = HORIZON if i == 5 else (i + 1) * step
        fill_region(view, 0, y, VW, y2, CEIL_0 + i)
        y = y2
    rest = VH - HORIZON
    step = rest // 6
    y = HORIZON
    for i in range(6):
        y2 = VH if i == 5 else HORIZON + (i + 1) * step
        fill_region(view, 0, y, VW, y2, FLOOR_0 + i)
        y = y2


def cast_walls(pos_x, pos_y, dir_x, dir_y, plane_x, plane_y):
    """DDA raycast, one vertical strip per ray. Fills zbuf."""
    grid = GRID
    mw = MW
    mh = MH
    half = VH >> 1
    inv_half_w = 2.0 / VW
    offset = STRIP_W * 0.5

    for strip in range(NUM_STRIPS):
        sx = strip * STRIP_W
        cam = (sx + offset) * inv_half_w - 1.0
        ray_x = dir_x + plane_x * cam
        ray_y = dir_y + plane_y * cam

        map_x = int(pos_x)
        map_y = int(pos_y)

        if ray_x == 0.0:
            delta_x = 1e30
        else:
            delta_x = abs(1.0 / ray_x)
        if ray_y == 0.0:
            delta_y = 1e30
        else:
            delta_y = abs(1.0 / ray_y)

        if ray_x < 0:
            step_x = -1
            side_x = (pos_x - map_x) * delta_x
        else:
            step_x = 1
            side_x = (map_x + 1.0 - pos_x) * delta_x
        if ray_y < 0:
            step_y = -1
            side_y = (pos_y - map_y) * delta_y
        else:
            step_y = 1
            side_y = (map_y + 1.0 - pos_y) * delta_y

        hit = 0
        side = 0
        for _ in range(64):                 # bounded: never loop forever
            if side_x < side_y:
                side_x += delta_x
                map_x += step_x
                side = 0
            else:
                side_y += delta_y
                map_y += step_y
                side = 1
            if map_x < 0 or map_y < 0 or map_x >= mw or map_y >= mh:
                break
            hit = grid[map_y * mw + map_x]
            if hit:
                break

        if not hit:
            zbuf[strip] = 1e9
            continue

        if side == 0:
            dist = side_x - delta_x
        else:
            dist = side_y - delta_y
        if dist < 0.05:
            dist = 0.05
        zbuf[strip] = dist

        line_h = int(VH / dist)
        y0 = half - (line_h >> 1)
        y1 = y0 + line_h
        if y0 < 0:
            y0 = 0
        if y1 > VH:
            y1 = VH
        if y1 <= y0:
            continue

        # Distance shading, plus one extra step of darkness on the
        # north/south faces so corners read as corners.
        if dist < 2.2:
            shade = 0
        elif dist < 4.5:
            shade = 1
        elif dist < 7.5:
            shade = 2
        else:
            shade = 3
        if side == 1 and shade < 3:
            shade += 1

        fill_region(view, sx, y0, sx + STRIP_W, y1,
                    WALL_0 + (hit - 1) * 4 + shade)


def draw_sprite(cols, art_w, art_h, sx0, sy0, pix_w, pix_h, depth):
    """Blit pre-merged column runs, clipped against zbuf when depth is
    given (world sprites) or unclipped when it is None (the weapon)."""
    col_w = pix_w / art_w
    row_h = pix_h / art_h
    for cx in range(art_w):
        x0 = int(sx0 + cx * col_w)
        x1 = int(sx0 + (cx + 1) * col_w)
        if x1 <= x0:
            x1 = x0 + 1
        if x1 <= 0 or x0 >= VW:
            continue
        if depth is not None:
            strip = ((x0 + x1) >> 1) // STRIP_W
            if strip < 0:
                strip = 0
            elif strip >= NUM_STRIPS:
                strip = NUM_STRIPS - 1
            if depth >= zbuf[strip]:
                continue                     # behind a wall
        if x0 < 0:
            x0 = 0
        if x1 > VW:
            x1 = VW
        for (ry0, ry1, color) in cols[cx]:
            y0 = int(sy0 + ry0 * row_h)
            y1 = int(sy0 + ry1 * row_h)
            if y1 <= y0:
                y1 = y0 + 1
            if y0 < 0:
                y0 = 0
            if y1 > VH:
                y1 = VH
            if y1 > y0:
                fill_region(view, x0, y0, x1, y1, color)


def sprite_transform(ex, ey, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y):
    """Camera-space (lateral, depth) for a world point, or None if the
    camera matrix is degenerate."""
    rx = ex - pos_x
    ry = ey - pos_y
    det = plane_x * dir_y - dir_x * plane_y
    if det == 0.0:
        return None
    inv = 1.0 / det
    tx = inv * (dir_y * rx - dir_x * ry)
    ty = inv * (-plane_y * rx + plane_x * ry)
    return tx, ty


def target_visible(tx, ty):
    """Is any part of a target at camera-space (tx, ty) unobstructed?

    Sampling only the centre strip means a pillar corner clipping the
    crosshair swallows shots at a monster standing in plain sight right
    next to it. Sweep the strips its sprite actually covers and let the
    shot through if any of them sees past the walls.
    """
    center = int((VW * 0.5) * (1.0 + tx / ty)) // STRIP_W
    half = int((VH / ty) * 0.32) // STRIP_W          # sprite half-width, in strips
    if half < 1:
        half = 1
    lo = center - half
    hi = center + half + 1
    if lo < 0:
        lo = 0
    if hi > NUM_STRIPS:
        hi = NUM_STRIPS
    for s in range(lo, hi):
        if ty < zbuf[s]:
            return True
    return False


def draw_pickups(spots, timers, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y):
    for i, (ax, ay) in enumerate(spots):
        if timers[i] > 0.0:                  # taken, still respawning
            continue
        t = sprite_transform(ax, ay, pos_x, pos_y,
                             dir_x, dir_y, plane_x, plane_y)
        if t is None:
            continue
        tx, ty = t
        if ty < 0.25:
            continue
        full_h = VH / ty
        pix_h = int(full_h * 0.22)
        pix_w = int(pix_h * AMMO_W / AMMO_H)
        if pix_h < 2 or pix_w < 2:
            continue
        screen_x = int((VW * 0.5) * (1.0 + tx / ty))
        sy0 = int(HORIZON + full_h * 0.5) - pix_h
        sx0 = screen_x - (pix_w >> 1)
        if sx0 >= VW or sx0 + pix_w <= 0:
            continue
        draw_sprite(AMMO_COLS, AMMO_W, AMMO_H, sx0, sy0, pix_w, pix_h, ty)


def draw_enemies(enemies, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y):
    # Painter's algorithm: farthest first so nearer monsters win.
    order = []
    for e in enemies:
        if e[E_HP] <= 0:
            continue
        dx = e[E_X] - pos_x
        dy = e[E_Y] - pos_y
        order.append((dx * dx + dy * dy, e))
    order.sort(key=lambda item: -item[0])

    for _, e in order:
        t = sprite_transform(e[E_X], e[E_Y], pos_x, pos_y,
                             dir_x, dir_y, plane_x, plane_y)
        if t is None:
            continue
        tx, ty = t
        if ty < 0.25:                        # behind or on top of the camera
            continue
        screen_x = int((VW * 0.5) * (1.0 + tx / ty))
        full_h = VH / ty
        pix_h = int(full_h * 0.86)
        pix_w = int(pix_h * ENEMY_W / ENEMY_H)
        if pix_h < 3 or pix_w < 3:
            continue
        floor_y = HORIZON + full_h * 0.5     # where this depth meets the floor
        sy0 = int(floor_y) - pix_h
        sx0 = screen_x - (pix_w >> 1)
        if sx0 >= VW or sx0 + pix_w <= 0:
            continue
        cols = ENEMY_COLS
        if e[E_HURT] > 0:                    # bright flash on taking a hit
            cols = ENEMY_HURT_COLS
        draw_sprite(cols, ENEMY_W, ENEMY_H, sx0, sy0, pix_w, pix_h, ty)


def draw_gun(bob, firing):
    y0 = VH - GUN_PIX_H + bob
    cols = GUN_COLS if firing else GUN_NOFLASH_COLS
    draw_sprite(cols, GUN_W, GUN_H, GUN_X0, y0, GUN_PIX_W, GUN_PIX_H, None)


def draw_crosshair():
    cx = VW >> 1
    cy = HORIZON
    fill_region(view, cx - 4, cy, cx - 1, cy + 1, CROSSHAIR)
    fill_region(view, cx + 2, cy, cx + 5, cy + 1, CROSSHAIR)
    fill_region(view, cx, cy - 4, cx + 1, cy - 1, CROSSHAIR)
    fill_region(view, cx, cy + 2, cx + 1, cy + 5, CROSSHAIR)


# ==================================================================
# The bot.
#
# Steering is deliberately split from the game: bot_think() returns the
# same (turn, walk, fire) triple a human's buttons would produce, and
# play() knows nothing about who generated it.
#
# Navigation is breadth-first search over the 16x16 grid. An earlier
# version just walked straight at its target, which wedges permanently
# on the first pillar it meets -- fine for a player who can see the
# problem and turn, fatal for an unattended demo.
# ==================================================================
BOT_TURN_DEAD = 0.10      # radians; inside this the bot counts as aimed
BOT_WALK_CONE = 0.55      # only walk while roughly facing the way it wants
BOT_STANDOFF = 1.7        # stop closing in and shoot from here
BOT_REPATH_S = 0.35       # how often to re-run the search
BOT_LOW_AMMO = 8
BOT_STUCK_S = 1.2         # no progress for this long -> shove sideways
BOT_STUCK_DIST = 0.25
BOT_EVADE_S = 0.7

_bfs_prev = [-1] * (MW * MH)
_bfs_queue = [0] * (MW * MH)


def next_waypoint(sx, sy, gx, gy):
    """Breadth-first search across open cells. Returns the first cell to
    step into on a shortest path from (sx, sy) to (gx, gy), or None if
    there is no route."""
    start = sy * MW + sx
    goal = gy * MW + gx
    if start == goal or GRID[goal]:
        return None

    prev = _bfs_prev
    for i in range(MW * MH):
        prev[i] = -1
    q = _bfs_queue
    q[0] = start
    prev[start] = start
    head = 0
    tail = 1
    found = False
    while head < tail:
        cur = q[head]
        head += 1
        if cur == goal:
            found = True
            break
        cy = cur // MW
        cx = cur - cy * MW
        if cx > 0:
            n = cur - 1
            if prev[n] < 0 and not GRID[n]:
                prev[n] = cur
                q[tail] = n
                tail += 1
        if cx < MW - 1:
            n = cur + 1
            if prev[n] < 0 and not GRID[n]:
                prev[n] = cur
                q[tail] = n
                tail += 1
        if cy > 0:
            n = cur - MW
            if prev[n] < 0 and not GRID[n]:
                prev[n] = cur
                q[tail] = n
                tail += 1
        if cy < MH - 1:
            n = cur + MW
            if prev[n] < 0 and not GRID[n]:
                prev[n] = cur
                q[tail] = n
                tail += 1
    if not found:
        return None

    cur = goal                                # walk the chain back to start
    while prev[cur] != start:
        cur = prev[cur]
        if cur == start:                      # already adjacent
            return None
    cy = cur // MW
    return cur - cy * MW, cy


def bot_think(st, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y,
              enemies, ammo, pickup_timers, now, dt):
    """Returns (turn, walk, fire): turn is -1/0/+1, the rest are bools."""
    # --- what is worth going to? ---
    prey = None
    prey_d2 = 1e9
    for e in enemies:
        if e[E_HP] <= 0:
            continue
        dx = e[E_X] - pos_x
        dy = e[E_Y] - pos_y
        d2 = dx * dx + dy * dy
        if d2 < prey_d2:
            prey_d2 = d2
            prey = e

    want_ammo = ammo <= BOT_LOW_AMMO or prey is None
    crate = None
    if want_ammo:
        crate_d2 = 1e9
        for i, (ax, ay) in enumerate(AMMO_SPOTS):
            if pickup_timers[i] > 0.0:
                continue
            dx = ax - pos_x
            dy = ay - pos_y
            d2 = dx * dx + dy * dy
            if d2 < crate_d2:
                crate_d2 = d2
                crate = (ax, ay)

    # --- can it shoot right now? ---
    fire = False
    prey_seen = False
    if prey is not None:
        t = sprite_transform(prey[E_X], prey[E_Y], pos_x, pos_y,
                             dir_x, dir_y, plane_x, plane_y)
        if t is not None:
            tx, ty = t
            if 0.3 < ty < SHOT_RANGE and target_visible(tx, ty):
                prey_seen = True
                # Aim tighter than the hit cone so it does not waste
                # rounds on shots that only just clip the edge.
                if ammo > 0 and abs(tx) <= SHOT_SPREAD * ty * 0.7:
                    fire = True

    # --- where is it heading? ---
    if crate is not None:
        goal = crate
    elif prey is not None:
        goal = (prey[E_X], prey[E_Y])
    else:
        return 0, False, False

    # A visible monster is worth walking straight at; otherwise route
    # around the level with the search.
    if prey_seen and crate is None:
        aim = goal
    else:
        gx = int(goal[0])
        gy = int(goal[1])
        cx = int(pos_x)
        cy = int(pos_y)
        if (now - st["path_at"] >= BOT_REPATH_S or st["wp"] is None
                or st["goal_cell"] != (gx, gy)):
            st["path_at"] = now
            st["goal_cell"] = (gx, gy)
            if (cx, cy) == (gx, gy):
                st["wp"] = goal
            else:
                nxt = next_waypoint(cx, cy, gx, gy)
                st["wp"] = goal if nxt is None else (nxt[0] + 0.5, nxt[1] + 0.5)
        aim = st["wp"]

    # --- unwedge: no progress while trying to move means something is
    # in the way that the grid search cannot see (a monster, or a wall
    # being hugged at a shallow angle). Turn hard and push. ---
    if now - st["stuck_at"] >= BOT_STUCK_S:
        sx, sy = st["stuck_pos"]
        dx = pos_x - sx
        dy = pos_y - sy
        if st["walked"] and (dx * dx + dy * dy) < BOT_STUCK_DIST * BOT_STUCK_DIST:
            st["evade"] = BOT_EVADE_S
            st["evade_dir"] = -st["evade_dir"]
        st["stuck_at"] = now
        st["stuck_pos"] = (pos_x, pos_y)
        st["walked"] = False

    if st["evade"] > 0.0:
        st["evade"] -= dt
        st["walked"] = True
        return st["evade_dir"], True, fire

    # --- steer ---
    tx = aim[0] - pos_x
    ty = aim[1] - pos_y
    ang = math.atan2(dir_x * ty - dir_y * tx, dir_x * tx + dir_y * ty)
    if ang < -BOT_TURN_DEAD:
        turn = -1
    elif ang > BOT_TURN_DEAD:
        turn = 1
    else:
        turn = 0

    walk = abs(ang) < BOT_WALK_CONE
    if walk and prey_seen and crate is None and prey_d2 < BOT_STANDOFF ** 2:
        walk = False                          # close enough; shoot instead
    if walk:
        st["walked"] = True
    return turn, walk, fire


def new_bot_state():
    return {"path_at": -99.0, "goal_cell": None, "wp": None,
            "stuck_at": 0.0, "stuck_pos": (0.0, 0.0), "walked": False,
            "evade": 0.0, "evade_dir": 1}


# ==================================================================
# HUD + LEDs
# ==================================================================
def update_hud(health, ammo, remaining, fps):
    hp_label.text = "HP %d" % health
    hp_label.color = 0x40FF60 if health > 60 else (
        0xFFD020 if health > 25 else 0xFF3020)
    ammo_label.text = "AMMO %d" % ammo
    imps_label.text = "IMPS %d" % remaining
    fps_label.text = "%d fps" % fps

    # Health bar inside its frame.
    fill_region(hud, 6, 36, VW - 6, 42, 0)
    span = VW - 12
    filled = int(span * max(0, health) / START_HEALTH)
    if filled > 0:
        color = 2 if health > 60 else (3 if health > 25 else 4)
        fill_region(hud, 6, 36, 6 + filled, 42, color)


def update_leds(health, flash):
    """5 pixels = a coarse health bar; `flash` overrides for one frame."""
    if flash == "fire":
        for i in range(5):
            pixels[i] = (255, 220, 120)
        pixels.show()
        return
    if flash == "hurt":
        for i in range(5):
            pixels[i] = (255, 0, 0)
        pixels.show()
        return
    if flash == "ammo":
        for i in range(5):
            pixels[i] = (60, 140, 255)
        pixels.show()
        return
    lit = health / START_HEALTH * 5.0
    for i in range(5):
        level = lit - i
        if level <= 0:
            pixels[i] = (0, 0, 0)
        else:
            if level > 1.0:
                level = 1.0
            if health > 60:
                pixels[i] = (0, int(180 * level), int(40 * level))
            elif health > 25:
                pixels[i] = (int(200 * level), int(160 * level), 0)
            else:
                pixels[i] = (int(220 * level), 0, 0)
    pixels.show()


def show_message(main, sub, color):
    msg_main.text = main
    msg_main.color = color
    msg_sub.text = sub
    msg_group.hidden = False


# ==================================================================
# One playthrough. Returns True if the level was cleared, False if the
# marine died.
# ==================================================================
def play():
    pos_x, pos_y, angle, spawns = roll_layout()
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    dir_x, dir_y = cos_a, sin_a
    plane_x, plane_y = -sin_a * FOV_PLANE, cos_a * FOV_PLANE

    health = START_HEALTH
    ammo = START_AMMO
    # Alternating sidle direction so a pack that jams on the same corner
    # splits and flows around both sides of it.
    enemies = [[sx, sy, ENEMY_HP, 0.0, 0.0, 0.0, 1 if i % 2 == 0 else -1]
               for i, (sx, sy) in enumerate(spawns)]
    remaining = len(enemies)
    pickup_timers = [0.0] * len(AMMO_SPOTS)

    bot = new_bot_state()
    fire_timer = 0.0
    flash_timer = 0.0
    bob_phase = 0.0
    led_flash = None
    hurt_flash = 0.0

    hud_dirty = True
    fps = 0
    frames = 0
    fps_at = time.monotonic()
    last = fps_at
    bot["stuck_at"] = fps_at
    bot["stuck_pos"] = (pos_x, pos_y)

    msg_group.hidden = True
    update_hud(health, ammo, remaining, 0)
    update_leds(health, None)

    while True:
        now = time.monotonic()
        dt = now - last
        last = now
        if dt > 0.15:            # a hitch shouldn't teleport anyone
            dt = 0.15
        if dt < 0.0:             # monotonic never goes backwards, but be safe
            dt = 0.0

        # ---- the bot takes its turn --------------------------------
        turn, walking, want_fire = bot_think(
            bot, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y,
            enemies, ammo, pickup_timers, now, dt)

        fired = want_fire and ammo > 0 and fire_timer <= 0.0

        if turn:
            angle += TURN_SPEED * dt * turn
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            dir_x, dir_y = cos_a, sin_a
            plane_x, plane_y = -sin_a * FOV_PLANE, cos_a * FOV_PLANE

        if walking:
            step = MOVE_SPEED * dt
            nx = pos_x + dir_x * step
            ny = pos_y + dir_y * step
            # Slide along walls instead of sticking to them.
            if not blocked(nx, pos_y, PLAYER_RADIUS):
                pos_x = nx
            if not blocked(pos_x, ny, PLAYER_RADIUS):
                pos_y = ny
            bob_phase += dt * 9.0
        else:
            bob_phase += dt * 1.5

        # ---- shooting ---------------------------------------------
        if fire_timer > 0.0:
            fire_timer -= dt
        if flash_timer > 0.0:
            flash_timer -= dt
        if fired:
            ammo -= 1
            fire_timer = FIRE_COOLDOWN
            flash_timer = 0.09
            led_flash = "fire"
            hud_dirty = True

            best = None
            best_depth = SHOT_RANGE
            for e in enemies:
                if e[E_HP] <= 0:
                    continue
                t = sprite_transform(e[E_X], e[E_Y], pos_x, pos_y,
                                     dir_x, dir_y, plane_x, plane_y)
                if t is None:
                    continue
                tx, ty = t
                if ty <= 0.3 or ty >= best_depth:
                    continue
                # Widen the cone with distance so far targets stay hittable.
                if abs(tx) > SHOT_SPREAD * ty:
                    continue
                if not target_visible(tx, ty):   # fully behind a wall
                    continue
                best = e
                best_depth = ty
            if best is not None:
                best[E_HP] -= SHOT_DAMAGE
                best[E_HURT] = 0.10
                if best[E_HP] <= 0:
                    remaining -= 1
                    print("Doom: imp down, %d left" % remaining)

        # ---- monsters ---------------------------------------------
        # Once the level is nearly clear the stragglers come looking for
        # the marine, so the demo always resolves instead of ending in a
        # long walk across an empty map.
        sight = ENEMY_SIGHT if remaining > 2 else 99.0
        for e in enemies:
            if e[E_HP] <= 0:
                continue
            if e[E_HURT] > 0.0:
                e[E_HURT] -= dt
            if e[E_COOL] > 0.0:
                e[E_COOL] -= dt
            dx = pos_x - e[E_X]
            dy = pos_y - e[E_Y]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > sight or dist < 0.0001:
                continue
            ux = dx / dist
            uy = dy / dist
            step = ENEMY_SPEED * dt

            if e[E_SIDLE] > 0.0:
                # Wedged last frame: slide sideways along the wall for a
                # moment instead of grinding into it forever.
                e[E_SIDLE] -= dt
                sx = -uy * e[E_SDIR]
                sy = ux * e[E_SDIR]
                moved = False
                nx = e[E_X] + sx * step
                ny = e[E_Y] + sy * step
                if not blocked(nx, e[E_Y], 0.2):
                    e[E_X] = nx
                    moved = True
                if not blocked(e[E_X], ny, 0.2):
                    e[E_Y] = ny
                    moved = True
                if not moved:
                    e[E_SDIR] = -e[E_SDIR]   # that way was a dead end too
            elif dist > ENEMY_REACH:
                nx = e[E_X] + ux * step
                ny = e[E_Y] + uy * step
                moved = False
                if not blocked(nx, e[E_Y], 0.2):
                    e[E_X] = nx
                    moved = True
                if not blocked(e[E_X], ny, 0.2):
                    e[E_Y] = ny
                    moved = True
                if not moved:
                    e[E_SIDLE] = ENEMY_SIDLE_S
            elif e[E_COOL] <= 0.0:
                e[E_COOL] = ENEMY_ATTACK_COOLDOWN
                health -= ENEMY_DAMAGE
                hurt_flash = 0.12
                led_flash = "hurt"
                hud_dirty = True

        # ---- ammo pickups -----------------------------------------
        for i, (ax, ay) in enumerate(AMMO_SPOTS):
            if pickup_timers[i] > 0.0:
                pickup_timers[i] -= dt
                continue
            if ammo >= MAX_AMMO:
                continue
            adx = ax - pos_x
            ady = ay - pos_y
            if adx * adx + ady * ady <= PICKUP_RADIUS * PICKUP_RADIUS:
                ammo = min(MAX_AMMO, ammo + PICKUP_AMMO)
                pickup_timers[i] = PICKUP_RESPAWN_S
                led_flash = "ammo"
                hud_dirty = True

        # ---- render -----------------------------------------------
        draw_bands()
        cast_walls(pos_x, pos_y, dir_x, dir_y, plane_x, plane_y)
        draw_pickups(AMMO_SPOTS, pickup_timers,
                     pos_x, pos_y, dir_x, dir_y, plane_x, plane_y)
        draw_enemies(enemies, pos_x, pos_y, dir_x, dir_y, plane_x, plane_y)
        draw_crosshair()
        bob = int(math.sin(bob_phase) * 3.0) + 3
        draw_gun(bob, flash_timer > 0.0)
        if hurt_flash > 0.0:
            hurt_flash -= dt
            # A red wash across the top of the view reads as "took a hit"
            # without the cost of blending every pixel.
            fill_region(view, 0, 0, VW, 6, WALL_0 + 3 * 4)

        display.refresh()

        # ---- housekeeping -----------------------------------------
        frames += 1
        if now - fps_at >= 1.0:
            fps = frames
            frames = 0
            fps_at = now
            hud_dirty = True
        if hud_dirty:
            update_hud(health, ammo, remaining, fps)
            hud_dirty = False

        update_leds(health, led_flash)
        led_flash = None

        if health <= 0:
            return False
        if remaining <= 0:
            return True


# ==================================================================
# Boot: title card, then run the demo forever.
# ==================================================================
try:                             # vary the layouts across power cycles too
    random.seed(time.monotonic_ns())
except AttributeError:
    pass

view.fill(CEIL_0 + 5)
show_message("DOOM", "autoplay demo", 0xFF3020)
display.refresh()
bl.value = True
update_leds(START_HEALTH, None)
time.sleep(2.0)

round_num = 0
while True:
    round_num += 1
    print("Doom: round %d begins" % round_num)
    won = play()
    print("Doom: round %d -> %s" % (round_num, "cleared" if won else "died"))

    for i in range(5):
        pixels[i] = (0, 120, 0) if won else (120, 0, 0)
    pixels.show()

    if won:
        show_message("VICTORY", "restarting...", 0x40FF60)
    else:
        show_message("GAME OVER", "restarting...", 0xFF3020)
    display.refresh()
    time.sleep(3.0)
