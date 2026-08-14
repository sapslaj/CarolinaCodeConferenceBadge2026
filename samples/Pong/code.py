"""
code.py -- Pong vs AI
====================================================================
Pong on the 128x160 TFT. You control the left paddle, a simple AI
controls the right. The ball speeds up a touch on every rally hit, and
the first side to 7 points wins the match. The 5 NeoPixels form a
score meter: green for your points, red for the CPU's, out of 7.

Controls
--------
  SW1 (IO1)   -- move paddle UP
  SW2 (IO2)   -- move paddle DOWN
  SW3 (IO43)  -- pause / resume; restart after a match ends

Total wins are kept in NVM (offset 72) as a single byte and don't
conflict with the Launcher, which uses bytes 0..40.
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
# Playfield
#   HUD strip = top 14px (score). Playfield y=14..160 (146px tall).
# ------------------------------------------------------------------
HUD_H = 14
PW, PH = 128, 160 - HUD_H

# Palette: 0 bg, 1 player, 2 ai, 3 ball, 4 net
pal = displayio.Palette(5)
pal[0] = 0x05050A
pal[1] = 0x00FF88
pal[2] = 0xFF4466
pal[3] = 0xFFFFFF
pal[4] = 0x202028

scene = displayio.Group()
hud_bg = displayio.Bitmap(128, HUD_H, 1)
hp = displayio.Palette(1); hp[0] = 0x101010
scene.append(displayio.TileGrid(hud_bg, pixel_shader=hp, x=0, y=0))

field = displayio.Bitmap(PW, PH, 5)
scene.append(displayio.TileGrid(field, pixel_shader=pal, x=0, y=HUD_H))

score_lbl = label.Label(terminalio.FONT, text="0   0", color=0xFFFFFF, x=50, y=4)
wins_lbl = label.Label(terminalio.FONT, text="WINS 0", color=0x606060, x=2, y=4)
scene.append(score_lbl); scene.append(wins_lbl)

msg_lbl = label.Label(terminalio.FONT, text="", color=0xFFFF00, scale=2, x=18, y=78)
msg_sub = label.Label(terminalio.FONT, text="", color=0xAAAAAA, x=30, y=104)
scene.append(msg_lbl); scene.append(msg_sub)
msg_lbl.hidden = True; msg_sub.hidden = True

display.root_group = scene


# ------------------------------------------------------------------
# NVM wins (offset 72)
# ------------------------------------------------------------------
def load_wins():
    try:
        v = microcontroller.nvm[72]
        return 0 if v == 0xFF else v
    except Exception:
        return 0


def save_wins(v):
    try:
        microcontroller.nvm[72] = v
    except Exception:
        pass


WINS = load_wins()
wins_lbl.text = "WINS %d" % WINS


# ------------------------------------------------------------------
# Game constants
# ------------------------------------------------------------------
PAD_W = 3
PAD_H = 24
BALL = 3
PLAYER_X = 4
AI_X = 128 - PAD_W - 4
PAD_SPEED = 2.4
AI_SPEED = 1.9
BALL_SPEED = 2.2
WIN_SCORE = 7


def serve(g, toward):
    g["bx"] = PW / 2.0
    g["by"] = PH / 2.0
    ang = random.uniform(-0.5, 0.5)
    g["bvx"] = BALL_SPEED * (1 if toward > 0 else -1)
    g["bvy"] = BALL_SPEED * ang
    g["spd"] = BALL_SPEED


def new_match():
    g = {
        "py": PH / 2.0 - PAD_H / 2.0,
        "ay": PH / 2.0 - PAD_H / 2.0,
        "ps": 0, "as": 0,
        "paused": False, "over": False,
    }
    serve(g, 1 if random.random() < 0.5 else -1)
    return g


def reset_paddles(g):
    g["py"] = PH / 2.0 - PAD_H / 2.0
    g["ay"] = PH / 2.0 - PAD_H / 2.0


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def draw(g):
    bitmaptools.fill_region(field, 0, 0, PW, PH, 0)
    # dashed centre net
    for y in range(0, PH, 8):
        bitmaptools.fill_region(field, PW // 2 - 1, y, PW // 2 + 1, min(y + 4, PH), 4)
    # paddles
    bitmaptools.fill_region(field, PLAYER_X, int(g["py"]),
                            PLAYER_X + PAD_W, int(g["py"]) + PAD_H, 1)
    bitmaptools.fill_region(field, AI_X, int(g["ay"]),
                            AI_X + PAD_W, int(g["ay"]) + PAD_H, 2)
    # ball
    bx, by = int(g["bx"]), int(g["by"])
    bitmaptools.fill_region(field, bx, by, bx + BALL, by + BALL, 3)
    score_lbl.text = "%d   %d" % (g["ps"], g["as"])
    display.refresh()


def score_meter(ps, as_):
    # green up to ps, red for as_, out of 7 -> 5 LEDs share 7 points (2pts/LED)
    for i in range(5):
        pixels[i] = (0, 0, 0)
    lit = (ps * 5 + WIN_SCORE - 1) // WIN_SCORE
    for i in range(lit):
        pixels[i] = (0, 200, 80)
    lit_r = (as_ * 5 + WIN_SCORE - 1) // WIN_SCORE
    for i in range(lit_r):
        pixels[4 - i] = (255, 40, 60) if pixels[4 - i] == (0, 0, 0) else pixels[4 - i]
    pixels.show()


def match_over(g, player_won):
    g["over"] = True
    global WINS
    if player_won:
        WINS += 1
        save_wins(WINS)
        wins_lbl.text = "WINS %d" % WINS
        pixels.fill((0, 200, 80))
    else:
        pixels.fill((255, 40, 40))
    pixels.show()
    msg_lbl.text = "YOU WIN!" if player_won else "CPU WINS"
    msg_lbl.color = 0x00FF66 if player_won else 0xFF4040
    msg_sub.text = "SW3 to play again"
    msg_lbl.hidden = False; msg_sub.hidden = False
    display.refresh()


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
game = new_match()
draw(game)
score_meter(0, 0)
bl.value = True

s1p = s2p = s3p = True

while True:
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    p3 = (not v3) and s3p
    s1p, s2p, s3p = v1, v2, v3

    if game["over"]:
        if p3:
            msg_lbl.hidden = True; msg_sub.hidden = True
            game = new_match()
            draw(game); score_meter(0, 0)
            time.sleep(0.2)
        time.sleep(0.02)
        continue

    # SW3 = pause toggle
    if p3:
        game["paused"] = not game["paused"]
        if game["paused"]:
            msg_lbl.text = "PAUSED"
            msg_lbl.color = 0xFFFF00
            msg_sub.text = "SW3 resume"
            msg_lbl.hidden = False; msg_sub.hidden = False
            display.refresh()
        else:
            msg_lbl.hidden = True; msg_sub.hidden = True
        time.sleep(0.15)

    if game["paused"]:
        time.sleep(0.02)
        continue

    # player paddle
    if not v1:
        game["py"] -= PAD_SPEED
    if not v2:
        game["py"] += PAD_SPEED
    game["py"] = clamp(game["py"], 0, PH - PAD_H)

    # AI: track the ball, but capped at AI_SPEED and only "engaged" when
    # the ball is heading toward it -- so it sometimes loses.
    target = game["by"] - PAD_H / 2.0
    if game["bvx"] > 0:
        if game["ay"] < target:
            game["ay"] = min(game["ay"] + AI_SPEED, target)
        elif game["ay"] > target:
            game["ay"] = max(game["ay"] - AI_SPEED, target)
    else:
        # drift back to centre when ball goes away
        centre = PH / 2.0 - PAD_H / 2.0
        if abs(game["ay"] - centre) > AI_SPEED:
            game["ay"] += AI_SPEED if game["ay"] < centre else -AI_SPEED
    game["ay"] = clamp(game["ay"], 0, PH - PAD_H)

    # ball
    game["bx"] += game["bvx"]
    game["by"] += game["bvy"]

    # top / bottom walls
    if game["by"] < 0:
        game["by"] = 0.0; game["bvy"] = -game["bvy"]
    elif game["by"] + BALL > PH:
        game["by"] = PH - BALL; game["bvy"] = -game["bvy"]

    # player paddle collision
    if game["bvx"] < 0 and game["bx"] <= PLAYER_X + PAD_W:
        if game["py"] <= game["by"] + BALL / 2 <= game["py"] + PAD_H:
            game["bx"] = PLAYER_X + PAD_W
            hit = (game["by"] + BALL / 2 - (game["py"] + PAD_H / 2)) / (PAD_H / 2)
            game["spd"] = min(game["spd"] + 0.18, 5.5)
            game["bvx"] = game["spd"]        # always rebounds rightward
            game["bvy"] = hit * game["spd"]

    # AI paddle collision
    if game["bvx"] > 0 and game["bx"] + BALL >= AI_X:
        if game["ay"] <= game["by"] + BALL / 2 <= game["ay"] + PAD_H:
            game["bx"] = AI_X - BALL
            hit = (game["by"] + BALL / 2 - (game["ay"] + PAD_H / 2)) / (PAD_H / 2)
            game["spd"] = min(game["spd"] + 0.18, 5.5)
            game["bvx"] = -game["spd"]
            game["bvy"] = hit * game["spd"]

    # scoring
    if game["bx"] < 0:
        game["as"] += 1
        score_meter(game["ps"], game["as"])
        if game["as"] >= WIN_SCORE:
            match_over(game, False)
        else:
            serve(game, -1); reset_paddles(game); draw(game)
            time.sleep(0.4)
    elif game["bx"] + BALL > PW:
        game["ps"] += 1
        score_meter(game["ps"], game["as"])
        if game["ps"] >= WIN_SCORE:
            match_over(game, True)
        else:
            serve(game, +1); reset_paddles(game); draw(game)
            time.sleep(0.4)

    draw(game)
    time.sleep(0.016)
