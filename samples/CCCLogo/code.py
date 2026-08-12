import board
import busio
import displayio
import fourwire
import adafruit_st7735r
import adafruit_imageload
import digitalio
import neopixel
import pwmio
import time

# NeoPixels — start off
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.025, auto_write=False)
pixels.fill((0, 0, 0))
pixels.show()

# PWM backlight — start dark for fade-in effect
bl = pwmio.PWMOut(board.IO5, frequency=1000, duty_cycle=0)

# Font chip CS — deselect so it stays off the SPI bus
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

# Display init (confirmed working: fourwire + adafruit_st7735r, CP 10.2.1)
displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7, baudrate=8_000_000
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=0, bgr=True, auto_refresh=False
)

# Load BMP (128×128, 8-bit indexed); logical display is 128×160 portrait
image, palette = adafruit_imageload.load(
    "/img/CarolinaCodeConference.bmp",
    bitmap=displayio.Bitmap,
    palette=displayio.Palette,
)

# Black background fills the full 128×160 space; image centred vertically
bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1)
bg_pal[0] = 0x000000

img_tile = displayio.TileGrid(image, pixel_shader=palette)
img_tile.y = (160 - 128) // 2  # 16 px from top

group = displayio.Group()
group.append(displayio.TileGrid(bg, pixel_shader=bg_pal))
group.append(img_tile)
display.root_group = group
display.refresh()


def hsv_to_rgb(h, s, v):
    if s == 0:
        r = g = b = v
    else:
        i = int(h * 6)
        f = h * 6 - i
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        i %= 6
        if i == 0:   r, g, b = v, t, p
        elif i == 1: r, g, b = q, v, p
        elif i == 2: r, g, b = p, v, t
        elif i == 3: r, g, b = p, q, v
        elif i == 4: r, g, b = t, p, v
        else:        r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)


FADE_IN, HOLD_BRIGHT, FADE_OUT = 0, 1, 2
FADE_SECS = 1.5   # full brightness takes 1.5 s
HOLD_SECS = 0.5   # stay bright for 0.5 s before fading out
fade_state = FADE_IN
state_t = time.monotonic()

px = 0.0      # bounce head position 0.0–4.0
px_dir = 1.0
LED_SPEED = 5.0   # pixels per second
hue = 0.0
HUE_RATE = 0.15   # full colour cycle every ~6.7 s

last_t = time.monotonic()

while True:
    now = time.monotonic()
    dt = now - last_t
    last_t = now
    elapsed = now - state_t

    # --- Backlight fade state machine ---
    if fade_state == FADE_IN:
        bl.duty_cycle = min(int(elapsed / FADE_SECS * 65535), 65535)
        if elapsed >= FADE_SECS:
            fade_state = HOLD_BRIGHT
            state_t = now
    elif fade_state == HOLD_BRIGHT:
        bl.duty_cycle = 65535
        if elapsed >= HOLD_SECS:
            fade_state = FADE_OUT
            state_t = now
    else:  # FADE_OUT
        bl.duty_cycle = max(int((1.0 - elapsed / FADE_SECS) * 65535), 0)
        if elapsed >= FADE_SECS:
            fade_state = FADE_IN
            state_t = now

    # --- LED bounce with colour trail ---
    hue = (hue + HUE_RATE * dt) % 1.0
    px += px_dir * LED_SPEED * dt
    if px >= 4.0:
        px = 4.0
        px_dir = -1.0
    elif px <= 0.0:
        px = 0.0
        px_dir = 1.0

    for i in range(5):
        bright = max(0.0, 1.0 - abs(i - px) * 0.6)
        r, g, b = hsv_to_rgb(hue, 1.0, bright)
        pixels[i] = (r, g, b)
    pixels.show()
