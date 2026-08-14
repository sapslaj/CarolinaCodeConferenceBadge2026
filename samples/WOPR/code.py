"""
WOPR -- Carolina Code Conference sample
========================================
A WarGames-inspired "War Operation Plan Response" terminal. Green
phosphor text types itself out onto a CRT-style display, a bank of
blinking status lights and the NeoPixel strip idle like a 1980s
military mainframe, and a game menu lets you pick a simulation to
run -- including the one you really shouldn't.

Controls
--------
  SW1 (IO1)   -- menu: move up      | busy: abort to menu
  SW2 (IO2)   -- menu: select/enter | busy: abort to menu
  SW3 (IO43)  -- menu: move down    | busy: abort to menu

Any button skips the boot typewriter sequence straight to the menu.
Hold SW1+SW3 together in the menu for ~1s for a secret shortcut straight
to Global Thermonuclear War. Leave the menu alone for 25s and WOPR gets
bored and plays a couple of games against itself until you touch a
button again.

Code design
-----------
- A tiny non-blocking "script" interpreter (`step_script`) drives the
  typewriter effect, pauses, and the DEFCON countdown one step at a
  time from the main loop -- no `time.sleep()` longer than a button
  poll, so the switches stay responsive during long sequences.
- Eight reusable row labels (`row_lbl`) are shared between the boot
  greeting, the menu list, and the game-loading/DEFCON text -- nothing
  is re-created at runtime, only `.text`/`.color` are reassigned.
- The status-light bank is one `displayio.Bitmap` + `bitmaptools.
  fill_region()` per cell (same technique as the WiFiScanner sample's
  signal bars), so redrawing 24 cells is cheap local memory work --
  the SPI bus only sees it on the next throttled `display.refresh()`.
- `set_panel_mode()` swaps the lights + NeoPixels between a calm
  green/amber idle flicker and a fast red "alert" flicker, shared by
  both the status-light bank and the LED strip so they read as one
  system.
"""

import time
import random
import board
import busio
import digitalio
import displayio
import fourwire
import neopixel
import terminalio
import bitmaptools
import adafruit_st7735r
from adafruit_display_text import label


# ------------------------------------------------------------------
# Hardware setup
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

# Font-ROM chip must stay deselected so the display owns the SPI bus
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False  # blank until the first frame is drawn

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
# Palette
# ------------------------------------------------------------------
GREEN      = 0x00FF41
DIM_GREEN  = 0x0A5A20
AMBER      = 0xFFB000
BLACK      = 0x000000

DEFCON_COLORS = {
    5: 0x00FF41,
    4: 0xADFF2F,
    3: 0xFFB000,
    2: 0xFF6A00,
    1: 0xFF1010,
}


# ------------------------------------------------------------------
# Scene
# ------------------------------------------------------------------
scene = displayio.Group()

bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1); bg_pal[0] = BLACK
scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

title = label.Label(terminalio.FONT, text="W.O.P.R.", scale=2, color=GREEN)
title.anchor_point = (0.5, 0.0)
title.anchored_position = (64, 4)
scene.append(title)

subtitle1 = label.Label(terminalio.FONT, text="WAR OPERATION PLAN",
                        scale=1, color=DIM_GREEN)
subtitle1.anchor_point = (0.5, 0.0)
subtitle1.anchored_position = (64, 21)
scene.append(subtitle1)

subtitle2 = label.Label(terminalio.FONT, text="RESPONSE",
                        scale=1, color=DIM_GREEN)
subtitle2.anchor_point = (0.5, 0.0)
subtitle2.anchored_position = (64, 30)
scene.append(subtitle2)

DIV_W = 118
div_bmp = displayio.Bitmap(DIV_W, 2, 1)
div_pal = displayio.Palette(1); div_pal[0] = DIM_GREEN
scene.append(displayio.TileGrid(div_bmp, pixel_shader=div_pal, x=5, y=40))

ROW_X = 2
ROWS_Y = [44, 54, 64, 74, 84, 94, 104, 114]
MAX_ROWS = len(ROWS_Y)

row_lbl = []
for ry in ROWS_Y:
    lbl = label.Label(terminalio.FONT, text="", color=GREEN, x=ROW_X, y=ry)
    scene.append(lbl)
    row_lbl.append(lbl)

cursor_lbl = label.Label(terminalio.FONT, text="", color=GREEN, x=ROW_X, y=ROWS_Y[0])
scene.append(cursor_lbl)

defcon_lbl = label.Label(terminalio.FONT, text="", scale=3, color=GREEN)
defcon_lbl.anchor_point = (0.5, 0.5)
defcon_lbl.anchored_position = (64, 80)
scene.append(defcon_lbl)

target_lbl = label.Label(terminalio.FONT, text="", color=AMBER)
target_lbl.anchor_point = (0.5, 0.5)
target_lbl.anchored_position = (64, 106)
scene.append(target_lbl)

# --- Status-light bank ---
CELL, GAP, COLS, ROWS = 8, 2, 12, 2
PANEL_W = COLS * (CELL + GAP) - GAP
PANEL_H = ROWS * (CELL + GAP) - GAP
PANEL_X = (128 - PANEL_W) // 2
PANEL_Y = 126

panel_bmp = displayio.Bitmap(PANEL_W, PANEL_H, 4)
panel_pal = displayio.Palette(4)
panel_pal[0] = 0x001005   # off
panel_pal[1] = GREEN
panel_pal[2] = AMBER
panel_pal[3] = 0xFF2000   # alert red
scene.append(displayio.TileGrid(panel_bmp, pixel_shader=panel_pal, x=PANEL_X, y=PANEL_Y))

footer_lbl = label.Label(terminalio.FONT, text="", color=DIM_GREEN, x=4, y=150)
scene.append(footer_lbl)

display.root_group = scene


# ------------------------------------------------------------------
# Status-light bank + NeoPixel idle animation
# ------------------------------------------------------------------
PANEL_MODE = "calm"
last_panel_t = 0.0
PANEL_INTERVAL = 0.09


def set_panel_mode(mode):
    global PANEL_MODE
    PANEL_MODE = mode


def panel_tick(t):
    global last_panel_t
    if t - last_panel_t < PANEL_INTERVAL:
        return
    last_panel_t = t

    for r in range(ROWS):
        for c in range(COLS):
            x1 = c * (CELL + GAP)
            y1 = r * (CELL + GAP)
            if PANEL_MODE == "alert":
                idx = 3 if random.random() < 0.55 else 0
            else:
                rv = random.random()
                if rv < 0.55:
                    idx = 1
                elif rv < 0.70:
                    idx = 2
                elif rv < 0.80:
                    idx = 0
                else:
                    idx = 1
            bitmaptools.fill_region(panel_bmp, x1, y1, x1 + CELL, y1 + CELL, idx)

    for i in range(5):
        if PANEL_MODE == "alert":
            pixels[i] = (255, 0, 0) if random.random() < 0.7 else (40, 0, 0)
        else:
            rv = random.random()
            if rv < 0.5:
                pixels[i] = (0, 180, 60)
            elif rv < 0.7:
                pixels[i] = (200, 140, 0)
            else:
                pixels[i] = (0, 60, 20)
    pixels.show()


# ------------------------------------------------------------------
# Non-blocking "script" interpreter
# ------------------------------------------------------------------
TYPE_SPEED = 0.035


def start_script(script):
    return {"script": script, "i": 0, "sub": None}


def draw_progress(frac):
    filled = int(18 * frac)
    row_lbl[2].text = "[" + ("#" * filled) + ("-" * (18 - filled)) + "]"


def step_script(st, t):
    """Advance one script tick. Returns True once the script is finished."""
    if st["i"] >= len(st["script"]):
        return True

    op = st["script"][st["i"]]
    kind = op[0]

    if kind == "type":
        _, row, text = op
        if st["sub"] is None:
            st["sub"] = {"shown": 0, "next_char": t}
        sub = st["sub"]
        if sub["shown"] < len(text) and t >= sub["next_char"]:
            sub["shown"] += 1
            row_lbl[row].text = text[: sub["shown"]]
            sub["next_char"] = t + TYPE_SPEED
            cursor_lbl.text = "_"
            cursor_lbl.x = ROW_X + sub["shown"] * 6
            cursor_lbl.y = ROWS_Y[row]
        if sub["shown"] >= len(text):
            st["i"] += 1
            st["sub"] = None
        return False

    if kind == "pause":
        _, dur = op
        if st["sub"] is None:
            st["sub"] = {"until": t + dur}
        if t >= st["sub"]["until"]:
            st["i"] += 1
            st["sub"] = None
        return False

    if kind == "clear":
        for lbl in row_lbl:
            lbl.text = ""
            lbl.color = GREEN
        cursor_lbl.text = ""
        target_lbl.text = ""
        st["i"] += 1
        return False

    if kind == "alert_on":
        set_panel_mode("alert")
        st["i"] += 1
        return False

    if kind == "alert_off":
        set_panel_mode("calm")
        st["i"] += 1
        return False

    if kind == "defcon":
        _, n, dur = op
        if st["sub"] is None:
            defcon_lbl.text = "DEFCON %d" % n
            defcon_lbl.color = DEFCON_COLORS[n]
            st["sub"] = {"until": t + dur, "next_city": t}
        sub = st["sub"]
        if t >= sub["next_city"]:
            target_lbl.text = "TARGET: " + random.choice(CITIES)
            sub["next_city"] = t + 0.18
        if t >= sub["until"]:
            st["i"] += 1
            st["sub"] = None
        return False

    if kind == "defcon_clear":
        defcon_lbl.text = ""
        target_lbl.text = ""
        st["i"] += 1
        return False

    if kind == "progress":
        _, dur = op
        if st["sub"] is None:
            st["sub"] = {"start": t}
        frac = (t - st["sub"]["start"]) / dur
        if frac > 1.0:
            frac = 1.0
        draw_progress(frac)
        if frac >= 1.0:
            st["i"] += 1
            st["sub"] = None
        return False

    # unknown op -- skip it rather than getting stuck
    st["i"] += 1
    return False


# ------------------------------------------------------------------
# Content
# ------------------------------------------------------------------
GREETING_SCRIPT = [
    ("type", 0, "GREETINGS PROFESSOR"),
    ("type", 1, "FALKEN."),
    ("pause", 1.3),
    ("clear",),
    ("type", 0, "SHALL WE PLAY A GAME?"),
    ("pause", 1.6),
]

# (full name used for the easter-egg check, menu label)
GAMES = [
    ("CHESS", "CHESS"),
    ("CHECKERS", "CHECKERS"),
    ("BACKGAMMON", "BACKGAMMON"),
    ("POKER", "POKER"),
    ("BLACK JACK", "BLACK JACK"),
    ("GIN RUMMY", "GIN RUMMY"),
    ("HEARTS", "HEARTS"),
    ("BRIDGE", "BRIDGE"),
    ("FALKENS MAZE", "FALKEN'S MAZE"),
    ("GLOBAL THERMONUCLEAR WAR", "THERMONUCLEAR WAR"),
]


def loading_script(game_name):
    return [
        ("clear",),
        ("type", 0, "LOADING:"),
        ("type", 1, game_name),
        ("progress", 1.4),
        ("clear",),
        ("type", 0, "SIMULATION COMPLETE"),
        ("type", 1, "GAME OVER -- YOU LOSE"),
        ("pause", 2.2),
    ]


CITIES = [
    "NORAD", "WASHINGTON DC", "MOSCOW", "LENINGRAD", "LONDON",
    "BEIJING", "BERLIN", "TOKYO", "SEATTLE", "OMAHA",
]

NUCLEAR_SCRIPT = [
    ("clear",),
    ("type", 0, "INITIATING GLOBAL"),
    ("type", 1, "THERMONUCLEAR WAR"),
    ("pause", 1.2),
    ("clear",),
    ("alert_on",),
    ("defcon", 5, 0.5),
    ("defcon", 4, 0.5),
    ("defcon", 3, 0.5),
    ("defcon", 2, 0.5),
    ("defcon", 1, 0.9),
    ("defcon_clear",),
    ("alert_off",),
    ("clear",),
    ("type", 0, "SIMULATION RUNAWAY"),
    ("pause", 1.3),
    ("clear",),
    ("type", 0, "A STRANGE GAME."),
    ("pause", 1.5),
    ("clear",),
    ("type", 0, "THE ONLY WINNING MOVE"),
    ("type", 1, "IS NOT TO PLAY."),
    ("pause", 2.2),
    ("clear",),
    ("type", 0, "HOW ABOUT A NICE"),
    ("type", 1, "GAME OF CHESS?"),
    ("pause", 3.0),
]


def attract_script():
    """Idle screensaver: WOPR announces it's bored and plays a couple of
    games against itself, picked at random from the non-nuclear list.
    CircuitPython's `random` module has no `sample()`, so two distinct
    indices are drawn by hand instead."""
    n = len(GAMES) - 1  # exclude nuclear war
    first = random.randrange(n)
    second = random.randrange(n)
    while second == first:
        second = random.randrange(n)
    picks = (first, second)
    script = [
        ("clear",),
        ("type", 0, "NO INPUT DETECTED."),
        ("pause", 1.0),
        ("type", 1, "WOPR CONTINUES ALONE."),
        ("pause", 1.6),
    ]
    for idx in picks:
        script += loading_script(GAMES[idx][1])
    script += [
        ("clear",),
        ("type", 0, "AWAITING INPUT..."),
        ("pause", 1.4),
    ]
    return script


# ------------------------------------------------------------------
# State machine
# ------------------------------------------------------------------
STATE_GREETING = "GREETING"
STATE_MENU = "MENU"
STATE_LOADING = "LOADING"
STATE_NUCLEAR = "NUCLEAR"
STATE_ATTRACT = "ATTRACT"

IDLE_TIMEOUT = 25.0   # seconds of no input at the menu before WOPR plays itself
COMBO_HOLD = 1.2      # seconds SW1+SW3 must be held together for the secret code

STATE = STATE_GREETING
script_st = start_script(GREETING_SCRIPT)

selected_idx = 0
visible_start = 0
last_input_t = 0.0
combo_start = None


def render_menu():
    for i in range(MAX_ROWS):
        idx = visible_start + i
        if idx < len(GAMES):
            marker = ">" if idx == selected_idx else " "
            text = (marker + GAMES[idx][1])[:21]
            row_lbl[i].text = text
            row_lbl[i].color = GREEN if idx == selected_idx else DIM_GREEN
        else:
            row_lbl[i].text = ""
    cursor_lbl.text = ""
    footer_lbl.text = "SW1/3 MOVE SW2 ENTER"


def enter_menu():
    global STATE, last_input_t
    STATE = STATE_MENU
    set_panel_mode("calm")
    defcon_lbl.text = ""
    target_lbl.text = ""
    cursor_lbl.text = ""
    last_input_t = time.monotonic()
    render_menu()


def abort_to_menu():
    global script_st
    for lbl in row_lbl:
        lbl.text = ""
    script_st = None
    enter_menu()


footer_lbl.text = ""

print("WOPR terminal booting")


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
sw1_prev = True
sw2_prev = True
sw3_prev = True
last_refresh = 0.0

while True:
    t = time.monotonic()

    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    pressed_sw1 = (not v1) and sw1_prev
    pressed_sw2 = (not v2) and sw2_prev
    pressed_sw3 = (not v3) and sw3_prev
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    if pressed_sw1 or pressed_sw2 or pressed_sw3:
        last_input_t = t

    if STATE == STATE_MENU:
        # Secret code: hold SW1+SW3 together to skip straight to the big one.
        if (not v1) and (not v3):
            if combo_start is None:
                combo_start = t
            elif t - combo_start >= COMBO_HOLD:
                combo_start = None
                last_input_t = t
                STATE = STATE_NUCLEAR
                script_st = start_script(NUCLEAR_SCRIPT)
                footer_lbl.text = "ANY KEY: ABORT"
        else:
            combo_start = None

        if STATE == STATE_MENU and pressed_sw1:
            selected_idx = (selected_idx - 1) % len(GAMES)
            if selected_idx < visible_start:
                visible_start = selected_idx
            elif selected_idx >= visible_start + MAX_ROWS:
                visible_start = selected_idx - MAX_ROWS + 1
            render_menu()
        if STATE == STATE_MENU and pressed_sw3:
            selected_idx = (selected_idx + 1) % len(GAMES)
            if selected_idx < visible_start:
                visible_start = selected_idx
            elif selected_idx >= visible_start + MAX_ROWS:
                visible_start = selected_idx - MAX_ROWS + 1
            render_menu()
        if STATE == STATE_MENU and pressed_sw2:
            chosen_full, chosen_label = GAMES[selected_idx]
            print("selected:", chosen_label)
            if chosen_full == "GLOBAL THERMONUCLEAR WAR":
                STATE = STATE_NUCLEAR
                script_st = start_script(NUCLEAR_SCRIPT)
            else:
                STATE = STATE_LOADING
                script_st = start_script(loading_script(chosen_label))
            footer_lbl.text = "ANY KEY: ABORT"
        if STATE == STATE_MENU and (t - last_input_t) >= IDLE_TIMEOUT:
            STATE = STATE_ATTRACT
            script_st = start_script(attract_script())
            footer_lbl.text = "ANY KEY: ABORT"
    else:
        if pressed_sw1 or pressed_sw2 or pressed_sw3:
            abort_to_menu()
        elif STATE == STATE_GREETING:
            if step_script(script_st, t):
                enter_menu()
        elif STATE == STATE_LOADING:
            if step_script(script_st, t):
                enter_menu()
        elif STATE == STATE_NUCLEAR:
            if step_script(script_st, t):
                enter_menu()
        elif STATE == STATE_ATTRACT:
            if step_script(script_st, t):
                enter_menu()

    panel_tick(t)

    if t - last_refresh > 0.05:
        display.refresh()
        last_refresh = t
        if not bl.value:
            bl.value = True

    time.sleep(0.01)
