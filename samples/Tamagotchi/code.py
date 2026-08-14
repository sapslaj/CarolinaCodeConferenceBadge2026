"""
code.py -- Tamagotchi (virtual pet)
====================================================================
A tiny virtual pet that lives on your badge. It gets hungry, bored and
tired over time -- feed it, play with it, and let it sleep. Its mood
shows on the display as an ASCII face and on the 5 NeoPixels as a
mood colour that gently breathes.

The pet's stats and its total age are saved in NVM (offset 76..81)
roughly every 20 seconds and whenever you interact, so it remembers
you across resets and power cycles. Because the badge has no battery
backed clock, the pet doesn't age or get hungry while powered off --
it's simply waiting, exactly as you left it.

Controls
--------
  SW1 (IO1)   -- FEED    (fills hunger; no-op if already full)
  SW2 (IO2)   -- PLAY    (raises fun; costs energy; no-op if exhausted)
  SW3 (IO43)  -- SLEEP / WAKE toggle
"""

import time
import math
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
# Display layout
# ------------------------------------------------------------------
scene = displayio.Group()
bg = displayio.Bitmap(128, 160, 1)
bp = displayio.Palette(1); bp[0] = 0x0A0E14
scene.append(displayio.TileGrid(bg, pixel_shader=bp, x=0, y=0))

title = label.Label(terminalio.FONT, text="VIRTUAL PET", color=0x00FFCC, x=30, y=6)
face_lbl = label.Label(terminalio.FONT, text="^_^", color=0xFFFF88, scale=3, x=37, y=46)
status_lbl = label.Label(terminalio.FONT, text="", color=0x80C0FF, x=20, y=78)
scene.append(title); scene.append(face_lbl); scene.append(status_lbl)

# Stat bars drawn on a bitmap in the lower half
BAR_X = 46
BAR_W = 74
BAR_H = 8
BAR_Y0 = 92
BAR_ROW = 18
bars_bmp = displayio.Bitmap(128, 60, 4)
bars_pal = displayio.Palette(4)
bars_pal[0] = 0x101418   # track
bars_pal[1] = 0xFFAA22   # hunger (food)
bars_pal[2] = 0x44AAFF   # fun (play)
bars_pal[3] = 0x66FF66   # energy (sleep)
scene.append(displayio.TileGrid(bars_bmp, pixel_shader=bars_pal, x=0, y=BAR_Y0))

lbl_food = label.Label(terminalio.FONT, text="FOOD", color=0xFFAA22, x=2, y=BAR_Y0 + 1)
lbl_fun = label.Label(terminalio.FONT, text="FUN", color=0x44AAFF, x=2, y=BAR_Y0 + BAR_ROW + 1)
lbl_nrg = label.Label(terminalio.FONT, text="ENER", color=0x66FF66, x=2, y=BAR_Y0 + 2 * BAR_ROW + 1)
scene.append(lbl_food); scene.append(lbl_fun); scene.append(lbl_nrg)

hint = label.Label(terminalio.FONT, text="S1 feed  S2 play  S3 sleep", color=0x404040, x=4, y=154)
scene.append(hint)

toast_lbl = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=20, y=150)
scene.append(toast_lbl)

display.root_group = scene


# ------------------------------------------------------------------
# NVM persistence (offset 76..81): hunger, fun, energy, age(3 BE)
# ------------------------------------------------------------------
def load_state():
    n = microcontroller.nvm
    if n[76] == 0xFF and n[77] == 0xFF:   # fresh flash
        return 80.0, 80.0, 80.0, 0
    hunger = n[76]
    fun = n[77]
    energy = n[78]
    age = (n[79] << 16) | (n[80] << 8) | n[81]
    return float(hunger), float(fun), float(energy), age


def save_state(hunger, fun, energy, age):
    n = microcontroller.nvm
    n[76] = int(hunger) & 0xFF
    n[77] = int(fun) & 0xFF
    n[78] = int(energy) & 0xFF
    n[79] = (age >> 16) & 0xFF
    n[80] = (age >> 8) & 0xFF
    n[81] = age & 0xFF


hunger, fun, energy, age = load_state()
sleeping = False


# ------------------------------------------------------------------
# Mood / face / LEDs
# ------------------------------------------------------------------
def dominant_need():
    needs = [("FOOD", hunger), ("FUN", fun), ("ENER", energy)]
    needs.sort(key=lambda x: x[1])
    return needs[0]


def face_for():
    if sleeping:
        return "Z z z", 0x88AAFF
    # urgent need first
    if hunger <= 30:
        return ">o<", 0xFFAA22
    if energy <= 30:
        return "-_-", 0x9966FF
    if fun <= 30:
        return ":(", 0x4488FF
    if hunger >= 70 and fun >= 70 and energy >= 70:
        return "^_^", 0xFFFF66
    return ":)", 0x88FF88


def mood_led_color():
    if sleeping:
        return (0, 80, 160)
    if hunger <= 30:
        return (255, 140, 30)
    if energy <= 30:
        return (120, 80, 200)
    if fun <= 30:
        return (60, 120, 255)
    if hunger >= 70 and fun >= 70 and energy >= 70:
        return (80, 220, 120)
    return (140, 200, 140)


# ------------------------------------------------------------------
# Bars + status rendering
# ------------------------------------------------------------------
def draw_bars():
    bitmaptools.fill_region(bars_bmp, 0, 0, 128, 60, 0)
    for i, (val, col) in enumerate(((hunger, 1), (fun, 2), (energy, 3))):
        y = i * BAR_ROW
        # track
        bitmaptools.fill_region(bars_bmp, BAR_X, y, BAR_X + BAR_W, y + BAR_H, 0)
        filled = int(BAR_W * max(0, min(100, val)) / 100)
        if filled:
            bitmaptools.fill_region(bars_bmp, BAR_X, y, BAR_X + filled, y + BAR_H, col)
    display.refresh()


def fmt_age(sec):
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    if h:
        return "age %dh %dm" % (h, m)
    return "age %dm" % m


def render():
    txt, col = face_for()
    face_lbl.text = txt
    face_lbl.color = col
    mode = "asleep  Z" if sleeping else "awake"
    status_lbl.text = "%s   %s" % (mode, fmt_age(age))
    draw_bars()
    display.refresh()


def show_toast(msg):
    toast_lbl.text = msg
    toast_lbl.color = 0xFFFF80


def clear_toast():
    toast_lbl.text = ""


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------
def feed():
    global hunger, energy
    if hunger >= 92:
        show_toast("too full!")
        return
    hunger = min(100, hunger + 30)
    energy = max(0, energy - 4)
    show_toast("nom nom  +30 food")


def play():
    global fun, energy, hunger
    if energy < 15:
        show_toast("too tired to play")
        return
    fun = min(100, fun + 25)
    energy = max(0, energy - 12)
    hunger = max(0, hunger - 5)
    show_toast("yay!  +25 fun")


def toggle_sleep():
    global sleeping
    sleeping = not sleeping
    show_toast("Zzz..." if sleeping else "good morning!")


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
render()
bl.value = True

last_tick = time.monotonic()
last_save = time.monotonic()
last_blink = time.monotonic()
blink_until = 0.0
toast_clear_at = 0.0
s1p = s2p = s3p = True

while True:
    now = time.monotonic()
    dt = now - last_tick
    last_tick = now

    # --- decay / regen ---
    if sleeping:
        energy = min(100, energy + dt / 4.0)
        hunger = max(0, hunger - dt / 12.0)
        # fun holds while asleep
    else:
        hunger = max(0, hunger - dt / 7.0)
        fun = max(0, fun - dt / 10.0)
        energy = max(0, energy - dt / 15.0)
    age += dt

    # --- buttons ---
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    p1 = (not v1) and s1p
    p2 = (not v2) and s2p
    p3 = (not v3) and s3p
    s1p, s2p, s3p = v1, v2, v3
    if p1:
        feed(); toast_clear_at = now + 1.2
    if p2:
        play(); toast_clear_at = now + 1.2
    if p3:
        toggle_sleep(); toast_clear_at = now + 1.2
        time.sleep(0.15)

    # --- render stats first (sets the normal face + bars + status) ---
    render()

    # --- blink animation (awake only), applied after render so it sticks ---
    if not sleeping and now - last_blink > 4.0:
        last_blink = now
        blink_until = now + 0.15
    if not sleeping and now < blink_until:
        face_lbl.text = "-_-"
        display.refresh()

    # --- clear transient toast after its window ---
    if toast_clear_at and now >= toast_clear_at:
        clear_toast()
        toast_clear_at = 0.0
        display.refresh()

    # --- LED breathing ---
    base = mood_led_color()
    breath = 0.6 + 0.4 * math.sin(now * 2.0) if sleeping else 0.7 + 0.3 * math.sin(now * 4.0)
    col = tuple(min(255, int(c * breath)) for c in base)
    pixels.fill(col)
    pixels.show()

    # --- persist roughly every 20 s ---
    if now - last_save > 20.0:
        save_state(hunger, fun, energy, int(age))
        last_save = now

    time.sleep(0.05)
