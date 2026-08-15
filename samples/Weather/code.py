"""
code_Weather.py -- Carolina Code Conference weather demo
========================================================
A single-file CircuitPython weather app for the ESP32-S3-DevKitC
conference kit (128x160 ST7735R TFT + 5-pixel NeoPixel strip).

What it does
------------
  1. Connects to WiFi
  2. Converts a US ZIP code to lat/lon      (api.zippopotam.us)
  3. Fetches current weather + 3-day forecast (api.open-meteo.com)
  4. Draws it on the TFT display
  5. Lights the 5 NeoPixels as a weather dashboard:
        pixel 0 -- current temperature color
        pixel 1 -- today's high
        pixel 2 -- tomorrow's high
        pixel 3 -- day-after high
        pixel 4 -- precipitation / condition indicator
  6. Press the onboard BOOT button (IO0) to refresh at any time.
     Otherwise it auto-refreshes every 15 minutes.

If anything goes wrong the display switches to a full-screen RED
error screen that tells you exactly which of the three values
below to double-check. Press BOOT to retry.

No API keys are required -- both web services are free and open.
WiFi credentials live in D:\settings.toml (shared across every
program on the drive). The ZIP code is set in this file.
"""

import os

# ==============================================================
#   Configuration
# ==============================================================

# --- WiFi credentials -- edit in D:\settings.toml ---
WIFI_SSID = os.getenv("WIFI_SSID", "your-wifi-name")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "your-wifi-password")

# --- ZIP code -- edit here ---
ZIP_CODE = "29605"  # 5-digit US ZIP
# ==============================================================


import gc
import time
import board
import busio
import digitalio
import displayio
import fourwire
import neopixel
import terminalio
import wifi
import socketpool
import ssl
import adafruit_requests
import adafruit_st7735r
from adafruit_display_text import label

# ------------------------------------------------------------------
# Hardware setup -- matches the working conference-kit samples
# ------------------------------------------------------------------
# NeoPixel strip (5 pixels on IO4)
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.3, auto_write=False)
pixels.fill((0, 0, 0))
pixels.show()

# Onboard BOOT button lives on GPIO0 (active LOW)
button = digitalio.DigitalInOut(board.IO0)
button.switch_to_input(pull=digitalio.Pull.UP)

# Font-ROM chip must stay deselected so the display owns the SPI bus
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

# Display backlight -- keep it off until the first frame is drawn
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

# ST7735R 128x160 TFT on SPI (IO12 clk, IO11 mosi)
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


# ------------------------------------------------------------------
# Color helpers
# ------------------------------------------------------------------
def temp_rgb(f):
    """Map a temperature (deg F) to an RGB tuple for the NeoPixels."""
    if f is None:
        return (30, 30, 30)  # unknown -- dim white
    if f < 32:
        return (0, 0, 255)  # icy blue
    if f < 50:
        return (0, 150, 255)  # cool blue
    if f < 70:
        return (0, 200, 0)  # comfy green
    if f < 85:
        return (255, 140, 0)  # warm orange
    return (255, 0, 0)  # hot red


def temp_hex(f):
    r, g, b = temp_rgb(f)
    return (r << 16) | (g << 8) | b


# WMO weather-code -> (short label, NeoPixel color)
WMO = {
    0: ("Clear", (255, 200, 40)),
    1: ("Mostly Clear", (255, 220, 100)),
    2: ("Partly Cloudy", (200, 200, 200)),
    3: ("Overcast", (120, 120, 120)),
    45: ("Fog", (150, 150, 170)),
    48: ("Icy Fog", (170, 200, 220)),
    51: ("Lt Drizzle", (80, 120, 200)),
    53: ("Drizzle", (60, 100, 200)),
    55: ("Hvy Drizzle", (40, 80, 200)),
    61: ("Light Rain", (30, 60, 220)),
    63: ("Rain", (20, 40, 220)),
    65: ("Heavy Rain", (0, 0, 220)),
    71: ("Light Snow", (220, 220, 255)),
    73: ("Snow", (200, 200, 255)),
    75: ("Heavy Snow", (180, 180, 255)),
    77: ("Snow Grains", (200, 200, 255)),
    80: ("Showers", (40, 80, 220)),
    81: ("Hvy Showers", (20, 40, 220)),
    82: ("Violent Rain", (0, 0, 180)),
    95: ("T-Storm", (180, 0, 220)),
    96: ("T-Storm+Hail", (180, 0, 220)),
    99: ("Severe Storm", (180, 0, 220)),
}


def wmo_label(code):
    return WMO.get(code, ("Unknown", (60, 60, 60)))[0]


def wmo_color(code):
    return WMO.get(code, ("Unknown", (60, 60, 60)))[1]


# ==================================================================
# Two display scenes: the normal weather view, and a big red error
# screen we switch to whenever something goes wrong.
# ==================================================================

# ------------------------------------------------------------------
# Scene 1 -- normal weather display
# ------------------------------------------------------------------
normal_scene = displayio.Group()

bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1)
bg_pal[0] = 0x000010  # very dark blue
normal_scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

# Header
lbl_zip = label.Label(terminalio.FONT, text="", color=0xFFFF00, x=4, y=8)
lbl_city = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=20)

# Current conditions
lbl_now_val = label.Label(terminalio.FONT, text="", scale=3, color=0xFFFFFF, x=8, y=48)
lbl_now_wx = label.Label(terminalio.FONT, text="", color=0xB0B0FF, x=4, y=78)
lbl_now_ext = label.Label(terminalio.FONT, text="", color=0x808080, x=4, y=92)

# 3-day forecast rows
lbl_d0 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=112)
lbl_d1 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=128)
lbl_d2 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=144)

# Small status footer
lbl_status = label.Label(terminalio.FONT, text="", color=0x606060, x=4, y=156)

for lb in (
    lbl_zip,
    lbl_city,
    lbl_now_val,
    lbl_now_wx,
    lbl_now_ext,
    lbl_d0,
    lbl_d1,
    lbl_d2,
    lbl_status,
):
    normal_scene.append(lb)


# ------------------------------------------------------------------
# Scene 2 -- full-screen error display
# ------------------------------------------------------------------
error_scene = displayio.Group()

err_bg = displayio.Bitmap(128, 160, 1)
err_pal = displayio.Palette(1)
err_pal[0] = 0x400000  # dark red -- unmistakably an error
error_scene.append(displayio.TileGrid(err_bg, pixel_shader=err_pal))

err_title = label.Label(terminalio.FONT, text="", scale=2, color=0xFFFF00, x=6, y=14)
error_scene.append(err_title)

err_lines = []
for i in range(9):
    lb = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=6, y=40 + i * 12)
    err_lines.append(lb)
    error_scene.append(lb)

err_footer = label.Label(
    terminalio.FONT, text="press BOOT to retry", color=0xFFC000, x=6, y=154
)
error_scene.append(err_footer)

# Start showing the normal scene by default
display.root_group = normal_scene


def show_error(title, lines):
    """Switch to the full-screen red error view."""
    err_title.text = title
    for i in range(len(err_lines)):
        err_lines[i].text = lines[i] if i < len(lines) else ""
    pixels.fill((60, 0, 0))
    pixels.show()
    display.root_group = error_scene
    display.refresh()

    # Mirror to serial console
    print()
    print("!" * 40)
    print("!! %s" % title)
    for ln in lines:
        if ln:
            print("!! " + ln)
    print("!! Press BOOT to retry")
    print("!" * 40)


def show_normal():
    """Switch back to the weather view (called after a successful refresh)."""
    display.root_group = normal_scene
    display.refresh()


# ------------------------------------------------------------------
# Turn error strings from CircuitPython into workshop-friendly
# messages that name the specific config variable to check.
# ------------------------------------------------------------------
def wifi_error_screen(e):
    msg = str(e).lower()
    if "auth" in msg or "handshake" in msg or "password" in msg:
        return (
            "WIFI AUTH",
            [
                "SSID:",
                '"%s"' % WIFI_SSID,
                "",
                "Auth failed --",
                "wrong password",
                "OR signal is",
                "too weak.",
                "",
                "Check WIFI_PASSWORD",
            ],
        )
    if "ssid" in msg or "not found" in msg or "no network" in msg:
        return (
            "SSID MISSING",
            [
                "Looking for:",
                '"%s"' % WIFI_SSID,
                "",
                "That network is",
                "not visible",
                "from here.",
                "",
                "Check WIFI_SSID",
                "in code.py",
            ],
        )
    if "timeout" in msg or "timed out" in msg:
        return (
            "WIFI TIMEOUT",
            [
                "SSID:",
                '"%s"' % WIFI_SSID,
                "",
                "Timed out while",
                "connecting.",
                "",
                "Signal is likely",
                "too weak -- move",
                "closer to router.",
            ],
        )
    # Anything else -- show the raw message truncated to fit
    return (
        "WIFI ERROR",
        [
            "SSID:",
            '"%s"' % WIFI_SSID,
            "",
            str(e)[:20],
            "",
            "Check WIFI_SSID",
            "and",
            "WIFI_PASSWORD",
            "in code.py",
        ],
    )


def api_error_screen(kind, e):
    if kind == "zip":
        return (
            "BAD ZIP",
            [
                "ZIP: %s" % ZIP_CODE,
                "",
                "Could not look",
                "up that ZIP:",
                str(e)[:18],
                "",
                "Check ZIP_CODE",
                "or network --",
                "must be 5 digits",
            ],
        )
    return (
        "WEATHER API",
        [
            "ZIP: %s" % ZIP_CODE,
            "",
            "Could not fetch",
            "weather data.",
            "",
            str(e)[:18],
            "",
            "Check network",
            "and ZIP_CODE",
        ],
    )


# ------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------
_session = None


def http():
    """Lazy-init HTTPS session shared by both API calls."""
    global _session
    if _session is None:
        pool = socketpool.SocketPool(wifi.radio)
        _session = adafruit_requests.Session(pool, ssl.create_default_context())
    return _session


def connect_wifi():
    lbl_status.text = "wifi: connecting..."
    lbl_status.color = 0xFFFF00
    display.refresh()
    pixels.fill((30, 30, 0))
    pixels.show()  # amber = connecting
    print("Connecting to WiFi:", WIFI_SSID)
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    print("  IP =", wifi.radio.ipv4_address)
    lbl_status.text = "wifi: %s" % wifi.radio.ipv4_address
    lbl_status.color = 0x00A000
    display.refresh()
    pixels.fill((0, 30, 0))
    pixels.show()  # green = connected
    time.sleep(0.3)
    pixels.fill((0, 0, 0))
    pixels.show()


def zip_to_latlon(zip_code):
    """US ZIP -> (lat, lon, city, state). Uses api.zippopotam.us (no key)."""
    url = "https://api.zippopotam.us/us/%s" % zip_code
    r = http().get(url)
    try:
        data = r.json()
    finally:
        r.close()
    # Bad ZIPs return an empty response body -- zippopotam has no places entry
    if not data or "places" not in data or not data["places"]:
        raise ValueError("zip lookup failed")
    place = data["places"][0]
    return (
        float(place["latitude"]),
        float(place["longitude"]),
        place["place name"],
        place["state abbreviation"],
    )


def fetch_weather(lat, lon):
    """Current conditions + 3-day forecast from open-meteo.com (no key)."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=%.4f&longitude=%.4f"
        "&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m"
        "&daily=temperature_2m_max,temperature_2m_min,weather_code"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph"
        "&timezone=auto&forecast_days=3"
    ) % (lat, lon)
    r = http().get(url)
    try:
        data = r.json()
    finally:
        r.close()
    return data


# ------------------------------------------------------------------
# Render weather to the display + NeoPixel strip
# ------------------------------------------------------------------
def render(weather, city, state):
    cur = weather["current"]
    daily = weather["daily"]

    now_t = cur["temperature_2m"]
    now_wc = cur["weather_code"]
    hum = cur["relative_humidity_2m"]
    wind = cur["wind_speed_10m"]

    # Header
    lbl_zip.text = "ZIP %s" % ZIP_CODE
    lbl_city.text = "%s, %s" % (city, state)

    # Now block
    lbl_now_val.text = "%d F" % round(now_t)
    lbl_now_val.color = temp_hex(now_t)
    lbl_now_wx.text = wmo_label(now_wc)
    lbl_now_ext.text = "H %d%%  Wind %d mph" % (hum, round(wind))

    # 3-day forecast rows
    rows = (lbl_d0, lbl_d1, lbl_d2)
    names = ("Today  ", "Tomor. ", "+2 day ")
    for i, lb in enumerate(rows):
        hi = daily["temperature_2m_max"][i]
        lo = daily["temperature_2m_min"][i]
        wc = daily["weather_code"][i]
        lb.text = "%s %3d/%3d  %s" % (names[i], round(hi), round(lo), wmo_label(wc))
        lb.color = temp_hex(hi)

    # NeoPixel dashboard
    pixels[0] = temp_rgb(now_t)
    pixels[1] = temp_rgb(daily["temperature_2m_max"][0])
    pixels[2] = temp_rgb(daily["temperature_2m_max"][1])
    pixels[3] = temp_rgb(daily["temperature_2m_max"][2])
    pixels[4] = wmo_color(now_wc)
    pixels.show()

    # Mirror to serial
    print()
    print("=" * 42)
    print(" %s, %s   (ZIP %s)" % (city, state, ZIP_CODE))
    print(
        " NOW: %5.1f F  %s   H%d%%  W%dmph"
        % (now_t, wmo_label(now_wc), hum, round(wind))
    )
    for i, name in enumerate(("Today   ", "Tomorrow", "+2 day  ")):
        print(
            " %s  %3.0f / %-3.0f F   %s"
            % (
                name,
                daily["temperature_2m_max"][i],
                daily["temperature_2m_min"][i],
                wmo_label(daily["weather_code"][i]),
            )
        )
    print("=" * 42)


# ------------------------------------------------------------------
# Main -- try_refresh() is the single entry point for both boot
# and the retry button. It classifies any failure into a specific
# error screen so attendees know exactly what to fix.
# ------------------------------------------------------------------
def try_refresh():
    # Reclaim heap before the TLS handshake -- mbedTLS needs a
    # contiguous chunk for its handshake buffers, and after building
    # both displayio scenes the free list is fragmented enough that
    # the handshake fails with -0x7280 on some builds.
    gc.collect()

    # Step 1: WiFi
    if not wifi.radio.connected:
        try:
            connect_wifi()
        except Exception as e:
            print("wifi failed:", e)
            title, lines = wifi_error_screen(e)
            show_error(title, lines)
            return False

    # Step 2: ZIP lookup
    try:
        lat, lon, city, state = zip_to_latlon(ZIP_CODE)
    except Exception as e:
        print("zip lookup failed:", e)
        title, lines = api_error_screen("zip", e)
        show_error(title, lines)
        return False

    # Step 3: Weather fetch + render
    gc.collect()
    try:
        weather = fetch_weather(lat, lon)
        render(weather, city, state)
    except Exception as e:
        print("weather fetch failed:", e)
        title, lines = api_error_screen("weather", e)
        show_error(title, lines)
        return False

    show_normal()
    lbl_status.text = "updated 0s ago"
    lbl_status.color = 0x606060
    display.refresh()
    return True


# Show something immediately, then turn the backlight on
lbl_zip.text = "ZIP %s" % ZIP_CODE
lbl_city.text = "starting up..."
display.refresh()
bl.value = True

try_refresh()
last_refresh = time.monotonic()
last_tick = time.monotonic()

REFRESH_SECONDS = 15 * 60  # auto-refresh every 15 minutes

while True:
    # ---- BOOT button = manual retry / refresh ----
    if not button.value:
        print("BOOT pressed -- retry")
        try_refresh()
        last_refresh = time.monotonic()
        # debounce
        while not button.value:
            time.sleep(0.05)

    # ---- Auto-refresh every REFRESH_SECONDS ----
    now = time.monotonic()
    elapsed = now - last_refresh
    if elapsed > REFRESH_SECONDS:
        try_refresh()
        last_refresh = time.monotonic()
    elif display.root_group is normal_scene and now - last_tick >= 1.0:
        # Once-per-second footer tick, only when weather is showing
        last_tick = now
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        if mins > 0:
            lbl_status.text = "updated %dm %ds ago" % (mins, secs)
        else:
            lbl_status.text = "updated %ds ago" % secs
        display.refresh()

    time.sleep(0.05)
