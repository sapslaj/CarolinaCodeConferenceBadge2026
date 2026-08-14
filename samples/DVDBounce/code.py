import board
import busio
import displayio
import fourwire
import digitalio
import neopixel
import adafruit_st7735r
import adafruit_imageload

# --- Backlight ---
_bl = digitalio.DigitalInOut(board.IO5)
_bl.direction = digitalio.Direction.OUTPUT
_bl.value = True

# --- NeoPixels ---
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.4, auto_write=False)

# --- Font chip CS — must stay high to keep it off the SPI bus ---
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

# --- Display (confirmed working: fourwire + adafruit_st7735r, CP 10.2.1) ---
# No MISO needed for the display; IO44 is the font chip's MISO only.
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

# --- Scene ---
scene = displayio.Group()
display.root_group = scene

bg_bitmap = displayio.Bitmap(128, 160, 1)
bg_palette = displayio.Palette(1)
bg_palette[0] = 0x0A0A0A
scene.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

# The logo is an 8-bit indexed BMP whose palette is a *coverage ramp*:
# index 0 is background (0% ink), the last index is solid logo (100% ink), and
# the ones between are the antialiased edges. Nothing in the file is colored --
# the animation loop rewrites the whole ramp every frame, so the soft edges
# take the current hue too instead of staying a fixed grey fringe.
logo, logo_palette = adafruit_imageload.load(
    "/samples/DVDBounce/dvd_logo.bmp",
    bitmap=displayio.Bitmap,
    palette=displayio.Palette,
)
logo_palette.make_transparent(0)  # let the background show through

dvd = displayio.TileGrid(logo, pixel_shader=logo_palette)
scene.append(dvd)

# Ink coverage per palette index. Index 0 is transparent and never written.
LEVELS = len(logo_palette)
SHADES = tuple(i / (LEVELS - 1) for i in range(LEVELS))


def tint_logo(r, g, b):
    """Recolor the ramp so the logo becomes (r, g, b) with its edges intact."""
    for i in range(1, LEVELS):
        c = SHADES[i]
        logo_palette[i] = (int(r * c) << 16) | (int(g * c) << 8) | int(b * c)


def hsv_to_rgb(h, s, v):
    if s == 0.0:
        c = int(v * 255)
        return c, c, c
    h6 = h * 6.0
    i = int(h6) % 6
    f = h6 - int(h6)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    if i == 0: return int(v*255), int(t*255), int(p*255)
    if i == 1: return int(q*255), int(v*255), int(p*255)
    if i == 2: return int(p*255), int(v*255), int(t*255)
    if i == 3: return int(p*255), int(q*255), int(v*255)
    if i == 4: return int(t*255), int(p*255), int(v*255)
    return int(v*255), int(p*255), int(q*255)


# Bounce boundaries derived from the bitmap; display is 128×160 portrait.
# A TileGrid's x/y IS its top-left corner, so the limits are plain subtraction
# -- no offset correction like a scaled Label needs.
LOGO_W, LOGO_H = logo.width, logo.height   # 88 × 53
MIN_X = MIN_Y = 0
MAX_X = 128 - LOGO_W
MAX_Y = 160 - LOGO_H

# DVD state
dvd_x, dvd_y = 20.0, 30.0
dvd_dx, dvd_dy = 1.8, 1.1

# NeoPixel bounce state
px_pos = 0.0
px_dir = 1

# Shared hue cycles 0.0 → 1.0 continuously; jumps on DVD wall hit
hue = 0.0

while True:
    hue = (hue + 0.004) % 1.0

    # -- NeoPixel bounce with fading trail --
    px_pos += px_dir * 0.18
    if px_pos >= 4.0:
        px_pos = 4.0
        px_dir = -1
    elif px_pos <= 0.0:
        px_pos = 0.0
        px_dir = 1

    for i in range(5):
        dist = abs(i - px_pos)
        brightness = max(0.0, 1.0 - dist * 0.6)
        r, g, b = hsv_to_rgb((hue + dist * 0.06) % 1.0, 1.0, brightness)
        pixels[i] = (r, g, b)
    pixels.show()

    # -- DVD logo bounce --
    dvd_x += dvd_dx
    dvd_y += dvd_dy
    bounced = False
    if dvd_x >= MAX_X:
        dvd_x = float(MAX_X)
        dvd_dx = -dvd_dx
        bounced = True
    elif dvd_x <= MIN_X:
        dvd_x = float(MIN_X)
        dvd_dx = -dvd_dx
        bounced = True
    if dvd_y >= MAX_Y:
        dvd_y = float(MAX_Y)
        dvd_dy = -dvd_dy
        bounced = True
    elif dvd_y <= MIN_Y:
        dvd_y = float(MIN_Y)
        dvd_dy = -dvd_dy
        bounced = True

    if bounced:
        hue = (hue + 0.23) % 1.0  # classic DVD screensaver color jump on wall hit

    dvd.x = int(dvd_x)
    dvd.y = int(dvd_y)
    r, g, b = hsv_to_rgb(hue, 1.0, 1.0)
    tint_logo(r, g, b)

    display.refresh()
