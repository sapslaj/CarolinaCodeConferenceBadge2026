import board
import busio
import displayio
import time
import digitalio
import neopixel
import fourwire
import adafruit_st7735r
import pwmio
from adafruit_display_text import label
import terminalio

# ---------------------------------------------------------------------------
# Morse code table
# ---------------------------------------------------------------------------
MORSE_TABLE = {
    '.-': 'A',    '-...': 'B',  '-.-.': 'C',  '-..': 'D',
    '.': 'E',     '..-.': 'F',  '--.': 'G',   '....': 'H',
    '..': 'I',    '.---': 'J',  '-.-': 'K',   '.-..': 'L',
    '--': 'M',    '-.': 'N',    '---': 'O',   '.--.': 'P',
    '--.-': 'Q',  '.-.': 'R',   '...': 'S',   '-': 'T',
    '..-': 'U',   '...-': 'V',  '.--': 'W',   '-..-': 'X',
    '-.--': 'Y',  '--..': 'Z',
    '-----': '0', '.----': '1', '..---': '2', '...--': '3',
    '....-': '4', '.....': '5', '-....': '6', '--...': '7',
    '---..': '8', '----.': '9',
}

# ---------------------------------------------------------------------------
# Switch 1 — IO1, pull-down wired (LOW when pressed); use internal Pull.UP
# ---------------------------------------------------------------------------
button = digitalio.DigitalInOut(board.IO1)
button.direction = digitalio.Direction.INPUT
button.pull = digitalio.Pull.UP   # True = released, False = pressed

# ---------------------------------------------------------------------------
# NeoPixels — IO4, 5 LEDs; used as input feedback
# ---------------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.4, auto_write=False)
pixels.fill((0, 0, 0))
pixels.show()

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
backlight = pwmio.PWMOut(board.IO5, frequency=1000, duty_cycle=65000)

# Font chip CS — must stay high so the font ROM doesn't corrupt the SPI bus
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7, baudrate=8_000_000
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=0, bgr=True
)

bg_bitmap = displayio.Bitmap(128, 160, 1)
bg_palette = displayio.Palette(1)
bg_palette[0] = 0x000000
group = displayio.Group()
group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

# "MORSE CODE" — 10 chars * 6px * scale 2 = 120px, x=4 fits 128px display
title_lbl = label.Label(terminalio.FONT, text="MORSE CODE", color=0xFF6600, scale=2, x=4, y=12)
group.append(title_lbl)

# Current input pattern (dots and dashes accumulate here while typing a letter)
pattern_lbl = label.Label(terminalio.FONT, text="", color=0xFFFFFF, scale=2, x=4, y=40)
group.append(pattern_lbl)

# Large decoded character — scale=5 (~30px wide), centered x=(128-30)//2=49
char_lbl = label.Label(terminalio.FONT, text=" ", color=0x00FF44, scale=5, x=49, y=95)
group.append(char_lbl)

# Accumulated decoded text — two lines at scale=1 (~21 chars each = 42 chars history)
text_lbl1 = label.Label(terminalio.FONT, text="", color=0x00AAFF, scale=1, x=2, y=131)
text_lbl2 = label.Label(terminalio.FONT, text="", color=0x00AAFF, scale=1, x=2, y=149)
group.append(text_lbl1)
group.append(text_lbl2)

display.root_group = group

# ---------------------------------------------------------------------------
# Timing constants — calibrated for ~10 WPM (PARIS standard, 1 unit = 80 ms)
# ---------------------------------------------------------------------------
UNIT             = 0.08
DOT_DASH_THRESH  = UNIT * 2.0   # < 160 ms = dot,  >= 160 ms = dash
CHAR_TIMEOUT     = UNIT * 4.5   # 360 ms gap after last release → decode
WORD_TIMEOUT     = UNIT * 9.0   # 720 ms gap → insert word space
DEBOUNCE         = 0.025        # 25 ms hardware debounce

MAX_LINE_CHARS   = 21     # chars per history line (128px / 6px per char)
MAX_TEXT_CHARS   = MAX_LINE_CHARS * 2


def update_text_display():
    if len(decoded_text) <= MAX_LINE_CHARS:
        text_lbl1.text = ""
        text_lbl2.text = decoded_text
    else:
        text_lbl1.text = decoded_text[-MAX_LINE_CHARS * 2:-MAX_LINE_CHARS]
        text_lbl2.text = decoded_text[-MAX_LINE_CHARS:]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
btn_state       = True    # debounced button (True = released)
last_edge_time  = 0.0
press_start     = 0.0
last_release    = 0.0
current_pattern = ""      # accumulates '.' and '-' for the current letter
decoded_text    = ""
char_pending    = False   # True while waiting for CHAR_TIMEOUT after a release
led_off_time    = 0.0     # monotonic time to extinguish LEDs (0 = stay on)


def set_leds(color, duration=0.0):
    global led_off_time
    pixels.fill(color)
    pixels.show()
    led_off_time = (time.monotonic() + duration) if duration > 0.0 else 0.0


def commit_char():
    global current_pattern, decoded_text, char_pending
    if not current_pattern:
        return
    letter = MORSE_TABLE.get(current_pattern, '?')
    decoded_text += letter
    if len(decoded_text) > MAX_TEXT_CHARS:
        decoded_text = decoded_text[-MAX_TEXT_CHARS:]
    char_lbl.text = letter
    update_text_display()
    current_pattern = ""
    pattern_lbl.text = ""
    char_pending = False
    set_leds((0, 200, 0), 0.4)   # green flash on successful decode


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
while True:
    now = time.monotonic()
    raw = button.value

    # --- Debounced edge detection ---
    if raw != btn_state and (now - last_edge_time) > DEBOUNCE:
        btn_state = raw
        last_edge_time = now

        if not btn_state:          # falling edge — button pressed
            press_start = now
            set_leds((255, 100, 0))        # amber while held

        else:                      # rising edge — button released
            duration = now - press_start
            if duration < DOT_DASH_THRESH:
                current_pattern += '.'
                set_leds((0, 80, 255), 0.15)    # blue flash = dot
            else:
                current_pattern += '-'
                set_leds((200, 0, 255), 0.15)   # purple flash = dash
            pattern_lbl.text = current_pattern
            last_release = now
            char_pending = True

    # --- Auto-extinguish LED feedback ---
    if led_off_time and now >= led_off_time:
        pixels.fill((0, 0, 0))
        pixels.show()
        led_off_time = 0.0

    # --- Character decode: fire after CHAR_TIMEOUT of silence ---
    if char_pending and btn_state and (now - last_release) > CHAR_TIMEOUT:
        commit_char()

    # --- Word space: insert ' ' after a longer pause ---
    if (decoded_text
            and not decoded_text.endswith(' ')
            and not current_pattern
            and last_release > 0
            and (now - last_release) > WORD_TIMEOUT):
        decoded_text += ' '
        if len(decoded_text) > MAX_TEXT_CHARS:
            decoded_text = decoded_text[-MAX_TEXT_CHARS:]
        update_text_display()
