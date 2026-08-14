"""
code.py -- Snake
====================================================================
Classic Snake on the 128x160 TFT. Steer with two buttons (turn left /
turn right, relative to the snake's heading), eat the red food, grow,
and don't crash into yourself or the wall. The 5 NeoPixels show how
long you've grown as a green bar that flashes white when you eat.

Controls
--------
  SW1 (IO1)   -- turn LEFT  (relative to current heading)
  SW2 (IO2)   -- turn RIGHT (relative to current heading)
  SW3 (IO43)  -- start / restart after a crash

High score persists in NVM (offset 64) across resets, so it survives
power cycling and survives the Launcher -- the Launcher stores its
own pick in bytes 0..40, and this sample only ever touches 64/65.
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
# Grid -- 16 cols x 18 rows of 8px cells. HUD strip = top 16px.
# ------------------------------------------------------------------
CELL = 8
COLS = 16
ROWS = 18
FIELD_Y = 16

# Palette: 0 bg, 1 head, 2 body, 3 food
pal = displayio.Palette(4)
pal[0] = 0x000000
pal[1] = 0x00FF66
pal[2] = 0x008833
pal[3] = 0xFF3030

scene = displayio.Group()
field = displayio.Bitmap(128, ROWS * CELL, 4)
scene.append(displayio.TileGrid(field, pixel_shader=pal, x=0, y=FIELD_Y))

hud_bg = displayio.Bitmap(128, 16, 1)
hud_pal = displayio.Palette(1); hud_pal[0] = 0x101010
scene.append(displayio.TileGrid(hud_bg, pixel_shader=hud_pal, x=0, y=0))

score_lbl = label.Label(terminalio.FONT, text="S:0", color=0xFFFF00, x=2, y=4)
high_lbl = label.Label(terminalio.FONT, text="HI:0", color=0x808080, x=80, y=4)
scene.append(score_lbl); scene.append(high_lbl)

go_lbl = label.Label(terminalio.FONT, text="GAME OVER", color=0xFF4040, scale=2, x=10, y=66)
go_sub = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=10, y=92)
go_hint = label.Label(terminalio.FONT, text="SW3 to restart", color=0x808080, x=10, y=108)
scene.append(go_lbl); scene.append(go_sub); scene.append(go_hint)
for l in (go_lbl, go_sub, go_hint):
    l.hidden = True

display.root_group = scene


# ------------------------------------------------------------------
# NVM high score (offset 64/65, 2 bytes big-endian; 0xFFFF = empty)
# ------------------------------------------------------------------
def load_high():
    try:
        hi = (microcontroller.nvm[64] << 8) | microcontroller.nvm[65]
        return 0 if hi == 0xFFFF else hi
    except Exception:
        return 0


def save_high(hi):
    try:
        microcontroller.nvm[64] = (hi >> 8) & 0xFF
        microcontroller.nvm[65] = hi & 0xFF
    except Exception:
        pass


HIGH = load_high()
high_lbl.text = "HI:%d" % HIGH


# ------------------------------------------------------------------
# Game state
# ------------------------------------------------------------------
# Directions as (dx, dy). Start moving RIGHT.
def turn_left(d):
    dx, dy = d
    return (dy, -dx)            # CCW


def turn_right(d):
    dx, dy = d
    return (-dy, dx)            # CW


def new_game():
    cx, cy = COLS // 4, ROWS // 2
    return {
        "snake": [(cx - 2, cy), (cx - 1, cy), (cx, cy)],
        "dir": (1, 0),
        "food": (COLS // 2, ROWS // 2),
        "score": 0,
        "tick": 0.16,
        "alive": True,
        "growing": 0,
        "eat_flash": 0.0,
    }


def place_food(g):
    g["eat_flash"] = time.monotonic() + 0.18
    while True:
        f = (random.randint(0, COLS - 1), random.randint(0, ROWS - 1))
        if f not in g["snake"]:
            g["food"] = f
            return


def step(g):
    """Advance the snake one cell. Returns True if still alive."""
    dx, dy = g["dir"]
    hx, hy = g["snake"][-1]
    nh = (hx + dx, hy + dy)
    # wall collision
    if not (0 <= nh[0] < COLS and 0 <= nh[1] < ROWS):
        return False
    # self collision (ignore the tail cell which will move, unless growing)
    body = g["snake"][1:] if g["growing"] == 0 else g["snake"]
    if nh in body:
        return False
    g["snake"].append(nh)
    if nh == g["food"]:
        g["score"] += 1
        g["growing"] += 1            # don't pop tail next few steps
        g["tick"] = max(0.06, g["tick"] - 0.004)
        place_food(g)
    if g["growing"] > 0:
        g["growing"] -= 1
    else:
        g["snake"].pop(0)
    return True


def draw(g):
    bitmaptools.fill_region(field, 0, 0, 128, ROWS * CELL, 0)
    fx, fy = g["food"]
    bitmaptools.fill_region(field, fx * CELL, fy * CELL,
                            fx * CELL + CELL, fy * CELL + CELL, 3)
    for i, (x, y) in enumerate(g["snake"]):
        c = 1 if i == len(g["snake"]) - 1 else 2
        bitmaptools.fill_region(field, x * CELL, y * CELL,
                                x * CELL + CELL, y * CELL + CELL, c)
    score_lbl.text = "S:%d" % g["score"]
    display.refresh()


def led_bar(g):
    # one LED per segment beyond the starting length of 3, capped at 5
    n = min(5, max(1, (len(g["snake"]) - 3) + 1))
    if time.monotonic() < g["eat_flash"]:
        pixels.fill((180, 180, 180))
    else:
        for i in range(5):
            pixels[i] = (0, 200, 60) if i < n else (0, 0, 0)
    pixels.show()


def game_over(g):
    g["alive"] = False
    pixels.fill((255, 0, 0)); pixels.show()
    go_sub.text = "score %d   high %d" % (g["score"], HIGH)
    for l in (go_lbl, go_sub, go_hint):
        l.hidden = False
    display.refresh()
    if g["score"] > HIGH:
        save_high(g["score"])


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
game = new_game()
place_food(game)
draw(game)
led_bar(game)
bl.value = True

last_step = time.monotonic()
sw1p = sw2p = sw3p = True

while True:
    now = time.monotonic()
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    p1 = (not v1) and sw1p
    p2 = (not v2) and sw2p
    p3 = (not v3) and sw3p
    sw1p, sw2p, sw3p = v1, v2, v3

    if not game["alive"]:
        if p3:
            for l in (go_lbl, go_sub, go_hint):
                l.hidden = True
            game = new_game()
            place_food(game)
            draw(game)
            led_bar(game)
            last_step = now
            time.sleep(0.15)
        time.sleep(0.02)
        continue

    # steering (relative turns)
    if p1:
        game["dir"] = turn_left(game["dir"])
    if p2:
        game["dir"] = turn_right(game["dir"])

    # step at the current tick rate
    if now - last_step >= game["tick"]:
        last_step = now
        if not step(game):
            game_over(game)
        else:
            draw(game)
            led_bar(game)
