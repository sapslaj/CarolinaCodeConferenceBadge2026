"""
code.py -- Tetris
====================================================================
Tetris on the 128x160 TFT. A 10x20 playfield sits on the left with a
side panel showing the next piece, score, lines, level and your best.
The 5 NeoPixels form a level meter -- one more LED lights up each time
you clear ten lines.

Controls
--------
  SW1 (IO1)      -- move LEFT
  SW2 (IO2)      -- move RIGHT
  SW3 (IO43)     -- rotate clockwise
  SW1 + SW2 held -- soft drop (piece falls fast while both are pressed)

Best score persists in NVM (offset 68/69) across resets and doesn't
touch the Launcher's saved pick, which lives in bytes 0..40.
"""

import time
import random
import board
import busio
import displayio
import fourwire
import digitalio
import neopixel
import microcontroller
import bitmaptools
import adafruit_st7735r
from adafruit_display_text import label
import terminalio

# ------------------------------------------------------------------
# Hardware
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.3, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

font_cs = digitalio.DigitalInOut(board.IO9); font_cs.switch_to_output(value=True)
bl = digitalio.DigitalInOut(board.IO5); bl.switch_to_output(value=False)

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
# Playfield geometry
#   board 10 wide x 20 tall, cell 7px -> 70 x 140, at (BX, BY)
#   side panel to the right for next-piece preview + stats
# ------------------------------------------------------------------
CELL = 7
BW, BH = 10, 20
BX, BY = 4, 16
BOARD_W = BW * CELL
BOARD_H = BH * CELL

# Next-piece preview: 4x4 cells of 5px -> 20x20
NCELL = 5
NB = 4
PREVIEW_X = 84
PREVIEW_Y = 22

# Palette: 0 bg, 1..7 piece colors, 8 ghost
pal = displayio.Palette(9)
pal[0] = 0x0A0A14
pal[1] = 0x00FFFF   # I  cyan
pal[2] = 0x3030FF   # J  blue
pal[3] = 0xFF8800   # L  orange
pal[4] = 0xFFFF00   # O  yellow
pal[5] = 0x00FF44   # S  green
pal[6] = 0xFF00FF   # T  magenta
pal[7] = 0xFF2233   # Z  red
pal[8] = 0x333344   # ghost

# Piece definitions: list of (cx, cy) relative cells, color index.
# Spawn orientation, normalised so minx=0, miny=0.
PIECES = [
    ([(0, 1), (1, 1), (2, 1), (3, 1)], 1),  # I
    ([(0, 0), (0, 1), (1, 1), (2, 1)], 2),  # J
    ([(2, 0), (0, 1), (1, 1), (2, 1)], 3),  # L
    ([(1, 0), (2, 0), (1, 1), (2, 1)], 4),  # O
    ([(1, 0), (2, 0), (0, 1), (1, 1)], 5),  # S
    ([(1, 0), (0, 1), (1, 1), (2, 1)], 6),  # T
    ([(0, 0), (1, 0), (1, 1), (2, 1)], 7),  # Z
]

scene = displayio.Group()

# Board background + grid frame
frame = displayio.Bitmap(128, 160, 1)
fp = displayio.Palette(1); fp[0] = 0x000008
scene.append(displayio.TileGrid(frame, pixel_shader=fp, x=0, y=0))

board = displayio.Bitmap(BOARD_W, BOARD_H, 9)
scene.append(displayio.TileGrid(board, pixel_shader=pal, x=BX, y=BY))

# Next-piece preview bitmap
preview = displayio.Bitmap(NB * NCELL, NB * NCELL, 9)
scene.append(displayio.TileGrid(preview, pixel_shader=pal, x=PREVIEW_X, y=PREVIEW_Y))

# Side-panel text
lbl_next = label.Label(terminalio.FONT, text="NEXT", color=0x808080, x=84, y=12)
lbl_score = label.Label(terminalio.FONT, text="0", color=0xFFFF00, x=84, y=52)
lbl_lines = label.Label(terminalio.FONT, text="L 0", color=0x8080FF, x=84, y=70)
lbl_level = label.Label(terminalio.FONT, text="LV 1", color=0x00FFAA, x=84, y=88)
lbl_high = label.Label(terminalio.FONT, text="HI 0", color=0x606060, x=84, y=106)
lbl_hint = label.Label(terminalio.FONT, text="S3 rot", color=0x404040, x=84, y=124)
lbl_hint2 = label.Label(terminalio.FONT, text="S1+S2 drop", color=0x404040, x=84, y=138)
for l in (lbl_next, lbl_score, lbl_lines, lbl_level, lbl_high, lbl_hint, lbl_hint2):
    scene.append(l)

# Game-over overlay (centred on the board)
go_lbl = label.Label(terminalio.FONT, text="GAME OVER", color=0xFF4040, scale=2, x=12, y=70)
go_sub = label.Label(terminalio.FONT, text="SW3 restart", color=0xAAAAAA, x=22, y=96)
scene.append(go_lbl); scene.append(go_sub)
go_lbl.hidden = True; go_sub.hidden = True

display.root_group = scene


# ------------------------------------------------------------------
# NVM best score (offset 68/69, 2 bytes big-endian)
# ------------------------------------------------------------------
def load_best():
    try:
        v = (microcontroller.nvm[68] << 8) | microcontroller.nvm[69]
        return 0 if v == 0xFFFF else v
    except Exception:
        return 0


def save_best(v):
    try:
        microcontroller.nvm[68] = (v >> 8) & 0xFF
        microcontroller.nvm[69] = v & 0xFF
    except Exception:
        pass


BEST = load_best()
lbl_high.text = "HI %d" % BEST


# ------------------------------------------------------------------
# Game helpers
# ------------------------------------------------------------------
def new_bag():
    """7-bag randomiser: shuffle all 7 pieces, then refill."""
    bag = list(range(7))
    # CircuitPython's random module has no shuffle(); do Fisher-Yates by hand.
    for i in range(len(bag) - 1, 0, -1):
        j = random.randint(0, i)
        bag[i], bag[j] = bag[j], bag[i]
    return bag


bag = new_bag()


def next_piece():
    global bag
    if not bag:
        bag = new_bag()
    return bag.pop()


def rotate_cells(cells):
    """Rotate CW: (x,y) -> (y, -x); then normalise to minx=0, miny=0."""
    rot = [(y, -x) for (x, y) in cells]
    minx = min(x for x, _ in rot)
    miny = min(y for _, y in rot)
    return [(x - minx, y - miny) for (x, y) in rot]


def fits(cells, ox, oy, grid):
    for (cx, cy) in cells:
        x = ox + cx
        y = oy + cy
        if x < 0 or x >= BW or y >= BH:
            return False
        if y >= 0 and grid[y][x] != 0:
            return False
    return True


def ghost_row(cells, ox, oy, grid):
    """Lowest row the piece can fall to from (ox, oy)."""
    while fits(cells, ox, oy + 1, grid):
        oy += 1
    return oy


def draw_board(grid, piece):
    cells, col, ox, oy = piece["cells"], piece["col"], piece["x"], piece["y"]
    gy = ghost_row(cells, ox, oy, grid)
    bitmaptools.fill_region(board, 0, 0, BOARD_W, BOARD_H, 0)
    for y in range(BH):
        for x in range(BW):
            v = grid[y][x]
            if v:
                bitmaptools.fill_region(
                    board, x * CELL, y * CELL, x * CELL + CELL, y * CELL + CELL, v)
    # ghost
    for (cx, cy) in cells:
        gx, gyy = ox + cx, gy + cy
        if 0 <= gyy < BH:
            bitmaptools.fill_region(board, gx * CELL, gyy * CELL,
                                    gx * CELL + CELL, gyy * CELL + CELL, 8)
    # current piece
    for (cx, cy) in cells:
        x, y = ox + cx, oy + cy
        if 0 <= y < BH:
            bitmaptools.fill_region(board, x * CELL, y * CELL,
                                    x * CELL + CELL, y * CELL + CELL, col)
    display.refresh()


def draw_preview(idx):
    bitmaptools.fill_region(preview, 0, 0, NB * NCELL, NB * NCELL, 0)
    cells, col = PIECES[idx]
    for (cx, cy) in cells:
        bitmaptools.fill_region(preview, cx * NCELL, cy * NCELL,
                                cx * NCELL + NCELL, cy * NCELL + NCELL, col)


def clear_lines(grid):
    kept = [row for row in grid if 0 in row]
    cleared = BH - len(kept)
    for _ in range(cleared):
        kept.insert(0, [0] * BW)
    return cleared, kept


def spawn(idx):
    cells, col = PIECES[idx]
    ox = (BW - (max(cx for cx, _ in cells) + 1)) // 2
    return {"cells": list(cells), "col": col, "x": ox, "y": 0, "idx": idx}


def gravity_ms(level):
    return max(0.08, 0.55 - (level - 1) * 0.06)


def level_meter(level):
    n = min(5, level)
    for i in range(5):
        pixels[i] = (0, 120, 255) if i < n else (0, 0, 0)
    pixels.show()


def reset_game():
    grid = [[0] * BW for _ in range(BH)]
    piece = spawn(next_piece())
    nxt = next_piece()
    draw_preview(nxt)
    return {
        "grid": grid, "piece": piece, "next": nxt,
        "score": 0, "lines": 0, "level": 1,
        "over": False, "drop": False,
    }


def lock_piece(g):
    p = g["piece"]
    for (cx, cy) in p["cells"]:
        y = p["y"] + cy
        x = p["x"] + cx
        if 0 <= y < BH:
            g["grid"][y][x] = p["col"]
    cleared, g["grid"] = clear_lines(g["grid"])
    if cleared:
        g["lines"] += cleared
        g["score"] += (0, 40, 100, 300, 1200)[cleared] * g["level"]
        new_level = g["lines"] // 10 + 1
        if new_level != g["level"]:
            g["level"] = new_level
            level_meter(g["level"])
    # spawn next
    g["piece"] = spawn(g["next"])
    g["next"] = next_piece()
    draw_preview(g["next"])
    if not fits(g["piece"]["cells"], g["piece"]["x"], g["piece"]["y"], g["grid"]):
        game_over(g)


def game_over(g):
    g["over"] = True
    pixels.fill((255, 0, 0)); pixels.show()
    go_lbl.hidden = False
    go_sub.hidden = False
    if g["score"] > BEST:
        save_best(g["score"])
    lbl_high.text = "HI %d" % max(g["score"], BEST)
    display.refresh()


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
game = reset_game()
draw_board(game["grid"], game["piece"])
level_meter(1)
bl.value = True

last_drop = time.monotonic()
s1p = s2p = s3p = True
DAS = 0.08     # auto-repeat delay for left/right when held

def try_move(g, dx):
    p = g["piece"]
    if fits(p["cells"], p["x"] + dx, p["y"], g["grid"]):
        p["x"] += dx
        draw_board(g["grid"], p)
        return True
    return False


def try_rotate(g):
    p = g["piece"]
    rot = rotate_cells(p["cells"])
    for (kx, ky) in ((0, 0), (-1, 0), (1, 0), (0, -1), (-2, 0), (2, 0)):
        if fits(rot, p["x"] + kx, p["y"] + ky, g["grid"]):
            p["cells"] = rot
            p["x"] += kx
            p["y"] += ky
            draw_board(g["grid"], p)
            return
    # rotation blocked -- ignore


def soft_drop_step(g):
    p = g["piece"]
    if fits(p["cells"], p["x"], p["y"] + 1, g["grid"]):
        p["y"] += 1
        g["score"] += 1
        return True
    lock_piece(g)
    draw_board(g["grid"], g["piece"])
    return False


# track held-button auto-repeat for left/right
move_dir = 0          # -1 left, +1 right, 0 none
move_hold_t = 0.0

while True:
    now = time.monotonic()
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    p1 = (not v1) and s1p
    p2 = (not v2) and s2p
    p3 = (not v3) and s3p
    s1p, s2p, s3p = v1, v2, v3

    if game["over"]:
        if p3:
            go_lbl.hidden = True; go_sub.hidden = True
            game = reset_game()
            draw_board(game["grid"], game["piece"])
            level_meter(1)
            last_drop = now
            time.sleep(0.2)
        time.sleep(0.02)
        continue

    both = (not v1) and (not v2)       # SW1 + SW2 held = soft drop

    # tap actions
    if p1 and not both:
        try_move(game, -1); move_dir = -1; move_hold_t = now
    if p2 and not both:
        try_move(game, +1); move_dir = +1; move_hold_t = now
    if p3:
        try_rotate(game)

    # auto-repeat while a single direction held
    if not both:
        if not v1 and not v2:
            move_dir = 0
        elif v1 and v2:
            # released: clear
            pass
    if move_dir and now - move_hold_t > 0.18 and not both:
        if (not v1 and move_dir == -1) or (not v2 and move_dir == +1):
            try_move(game, move_dir)
            move_hold_t = now

    # gravity / soft drop
    interval = 0.03 if both else gravity_ms(game["level"])
    if now - last_drop >= interval:
        last_drop = now
        if both:
            soft_drop_step(game)
        else:
            p = game["piece"]
            if fits(p["cells"], p["x"], p["y"] + 1, game["grid"]):
                p["y"] += 1
            else:
                lock_piece(game)
            draw_board(game["grid"], game["piece"])

    # update side-panel numbers
    lbl_score.text = "%d" % game["score"]
    lbl_lines.text = "L %d" % game["lines"]
    lbl_level.text = "LV %d" % game["level"]

    time.sleep(0.01)
