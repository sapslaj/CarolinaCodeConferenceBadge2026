"""
code.py -- Animated GIF player for the Carolina Code Conference 2026 badge.
==========================================================================
Plays animated GIFs full-screen, either from a `/gifs/` folder on the
badge or pulled fresh off GIPHY over WiFi.

Two sources, and the first one always works
-------------------------------------------
  LOCAL  -- plays every .gif in /gifs/ on the badge. No WiFi, no keys,
            no writes to the filesystem. This is the default.
  GIPHY  -- asks the GIPHY API for a G-rated GIF, downloads the smallest
            rendition, and plays it. The default tag is `trending`, which
            fetches what is popular right now and lets SW1 walk the top
            few; the other tags roll a random GIF each time.

Nothing is bundled from GIPHY. Their API is licensed for fetching and
displaying GIFs at runtime, which is what this does -- redistributing
somebody's GIF by committing it to a repository is a different thing
and not one this sample does for you.

GIPHY mode has one hard requirement that has nothing to do with this
code: **the badge has to be able to write to its own filesystem.**
`gifio.OnDiskGif` can only open a *file*, so a downloaded GIF has to
land on the drive first, and CircuitPython refuses to mount the drive
writable while a host computer holds write access to it.

In practice that means GIPHY mode works when the badge is running on
battery, and reports the problem instead of failing mysteriously when
it is plugged into a computer. README.md has the boot.py workaround,
and the serial console recovery if you use it and regret it.

Setup
-----
Put these in settings.toml on the CIRCUITPY drive:

    WIFI_SSID      = "your-network"
    WIFI_PASSWORD  = "your-password"
    GIPHY_API_KEY  = "your-key"      # free: developers.giphy.com

Controls
--------
  SW1  -- next GIF (in GIPHY mode, fetches a new one)
  SW2  -- next tag (cycles the TAGS list below)
  SW3  -- switch source, LOCAL <-> GIPHY

Notes on the GIF format
-----------------------
`gifio.OnDiskGif` streams frames off the filesystem, so a long GIF
costs no more RAM than a short one -- but it decodes each frame into a
`width x height x 2` byte bitmap, and this board has 512 KB of SRAM and
no PSRAM. A 100x100 GIF needs 20 KB, which is fine; a 480x270 one needs
259 KB, which is not. That is why the GIPHY fetch asks for the
`fixed_width_small` rendition (100 px wide) and falls back to
`preview_gif` (capped at 50 KB).

Frames come out of the decoder as big-endian RGB565, which is the
opposite byte order from what displayio expects, hence the
`Colorspace.RGB565_SWAPPED` converter. Get that wrong and the picture
looks like static.
"""

# --- backlight off FIRST, before the slow adafruit imports ---------
# Same trick the launcher uses: the panel powers up bright white, so
# claim IO5 and drive it low before spending seconds on imports.
import board
import digitalio
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

import os
import gc
import time
import busio
import storage
import displayio
import fourwire
import terminalio
import neopixel
import adafruit_st7735r
from adafruit_display_text import label

# `gifio` is a built-in module on the ESP32-S3 CircuitPython build. If a
# build somehow lacks it there is no fallback worth writing -- decoding
# LZW frames in Python would be far too slow -- so say so and stop.
try:
    import gifio
except ImportError:
    gifio = None


# ==================================================================
# Configuration -- everything lives in settings.toml so the same
# credentials serve every sample. See settings.toml.example.
# ==================================================================
WIFI_SSID = os.getenv("WIFI_SSID", "")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "")
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "")

LOCAL_DIR = "/gifs"
CACHE_PATH = "/gifs/_giphy.gif"      # one file, rewritten every fetch

# Tags SW2 cycles through. "trending" is special: it asks GIPHY for
# what is popular right now rather than for a tag, and SW1 walks the
# top few instead of rolling a new random one. Keep the rest wholesome
# -- this screen is on your chest at a conference.
TRENDING = "trending"
TRENDING_TOP = 5                      # how many of the top GIFs to cycle
TAGS = (TRENDING, "cat", "dog", "robot", "space", "pixel art", "coffee")

# GIPHY renditions, smallest sensible first. `fixed_width_small` is
# 100 px wide which suits a 128 px screen; `preview_gif` is capped at
# 50 KB but its dimensions are unpredictable.
RENDITIONS = ("fixed_width_small", "preview_gif", "downsized_small")

RATING = "g"                          # G-rated only
HTTP_TIMEOUT = 20
MAX_BYTES = 320 * 1024                # refuse anything silly-sized

VW = 128
VH = 160


# ==================================================================
# Hardware
# ==================================================================
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.25, auto_write=False)


def _btn(pin):
    b = digitalio.DigitalInOut(pin)
    b.switch_to_input(pull=digitalio.Pull.UP)
    return b


sw1 = _btn(board.IO1)
sw2 = _btn(board.IO2)
sw3 = _btn(board.IO43)

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
    width=VW,
    height=VH,
    rotation=0,
    bgr=True,
    auto_refresh=False,
)


# ==================================================================
# Scene. Two groups swapped in and out of the display: a status card
# for messages, and the GIF itself.
# ==================================================================
status_group = displayio.Group()

bg = displayio.Bitmap(VW, VH, 1)
bg_pal = displayio.Palette(1)
bg_pal[0] = 0x000010
status_group.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

title_lbl = label.Label(terminalio.FONT, text="GIF PLAYER", color=0x00FFFF, scale=2)
title_lbl.anchor_point = (0.5, 0.5)
title_lbl.anchored_position = (VW // 2, 30)
status_group.append(title_lbl)

status_lbl = label.Label(terminalio.FONT, text="", color=0xFFFF00)
status_lbl.anchor_point = (0.5, 0.5)
status_lbl.anchored_position = (VW // 2, 62)
status_group.append(status_lbl)

detail_lbl = label.Label(terminalio.FONT, text="", color=0xA0A0A0)
detail_lbl.anchor_point = (0.5, 0.5)
detail_lbl.anchored_position = (VW // 2, 80)
status_group.append(detail_lbl)

detail2_lbl = label.Label(terminalio.FONT, text="", color=0xA0A0A0)
detail2_lbl.anchor_point = (0.5, 0.5)
detail2_lbl.anchored_position = (VW // 2, 94)
status_group.append(detail2_lbl)

hint_lbl = label.Label(terminalio.FONT, text="S1:next S2:tag S3:src",
                       color=0x606060)
hint_lbl.anchor_point = (0.5, 0.5)
hint_lbl.anchored_position = (VW // 2, 152)
status_group.append(hint_lbl)

display.root_group = status_group


# terminalio.FONT is 6 px wide, so a 128 px line holds 21 characters.
# Truncating here rather than at every call site means the serial log
# keeps the full text -- which is where the useful half of an error
# message usually lives.
SCREEN_CHARS = 21


def show_status(msg, detail="", detail2="", color=0xFFFF00):
    status_lbl.text = msg[:SCREEN_CHARS]
    status_lbl.color = color
    detail_lbl.text = detail[:SCREEN_CHARS]
    detail2_lbl.text = detail2[:SCREEN_CHARS]
    display.root_group = status_group
    display.refresh()
    if msg:
        print("GifPlayer: %s %s %s" % (msg, detail, detail2))


# ==================================================================
# LEDs -- a small activity indicator, off while a GIF is playing so
# it doesn't compete with the screen.
# ==================================================================
def leds(rgb):
    for i in range(5):
        pixels[i] = rgb
    pixels.show()


# ==================================================================
# Filesystem
# ==================================================================
def list_local_gifs():
    try:
        names = os.listdir(LOCAL_DIR)
    except OSError:
        return []
    out = []
    for n in names:
        if not n.lower().endswith(".gif") or n.startswith("."):
            continue
        path = "%s/%s" % (LOCAL_DIR, n)
        if path == CACHE_PATH:
            continue          # the GIPHY scratch file, not something you added
        out.append(path)
    out.sort()
    return out


def make_writable():
    """Try to get write access to the badge's own filesystem.

    CircuitPython hands write access to exactly one of the badge and the
    host computer. Plugged into USB the host usually wins, and remount
    raises -- which is a configuration problem, not a bug, so callers
    turn this into an explanation rather than a traceback.
    """
    try:
        storage.remount("/", readonly=False)
        return True
    except Exception as exc:
        print("GifPlayer: filesystem is read-only:", exc)
        return False


def make_readonly():
    """Hand the filesystem back so the host can see what changed."""
    try:
        storage.remount("/", readonly=True)
    except Exception:
        pass


def ensure_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass                          # already there, or not writable


# ==================================================================
# Network. Imported lazily: a badge in LOCAL mode should not pay for
# the wifi stack, and this sample has to keep working on a build with
# no credentials configured at all.
# ==================================================================
_session = None
_wifi_up = False


def connect_wifi():
    global _session, _wifi_up
    if _wifi_up:
        return True
    if not WIFI_SSID:
        show_status("no wifi config", "set WIFI_SSID in", "settings.toml",
                    color=0xFF6060)
        return False

    import wifi
    import ssl
    import socketpool
    import adafruit_requests

    show_status("connecting...", WIFI_SSID)
    try:
        wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    except Exception as exc:
        show_status("wifi failed", str(exc), color=0xFF6060)
        return False

    pool = socketpool.SocketPool(wifi.radio)
    _session = adafruit_requests.Session(pool, ssl.create_default_context())
    _wifi_up = True
    print("GifPlayer: wifi up, ip =", wifi.radio.ipv4_address)
    return True


def giphy_pick(tag, slot):
    """Ask GIPHY for a GIF and return the best URL for us.

    `trending` returns a list of what is popular right now and `slot`
    picks one of them, so SW1 walks the top few. Every other tag uses
    the random endpoint, where `data` is a single object instead.

    Returns (url, title) or (None, reason). Only the URL and title are
    kept out of the response -- the JSON is several kilobytes and this
    board does not have the headroom to hang onto it.
    """
    if tag == TRENDING:
        url = ("https://api.giphy.com/v1/gifs/trending"
               "?api_key=%s&limit=%d&rating=%s"
               % (GIPHY_API_KEY, TRENDING_TOP, RATING))
    else:
        url = ("https://api.giphy.com/v1/gifs/random"
               "?api_key=%s&tag=%s&rating=%s"
               % (GIPHY_API_KEY, tag.replace(" ", "+"), RATING))
    try:
        r = _session.get(url, timeout=HTTP_TIMEOUT)
    except Exception as exc:
        return None, "request failed: %s" % exc

    try:
        if r.status_code != 200:
            return None, "HTTP %d" % r.status_code
        data = r.json()
    except Exception as exc:
        return None, "bad response: %s" % exc
    finally:
        r.close()

    payload = data.get("data")
    # A key that is out of quota still returns 200 with an empty object.
    if not payload:
        return None, "bad key or quota"
    if isinstance(payload, list):     # trending gives a list, random one object
        payload = payload[slot % len(payload)]
    images = payload.get("images", {})
    title = payload.get("title", "")

    for name in RENDITIONS:
        rendition = images.get(name)
        if rendition and rendition.get("url"):
            print("GifPlayer: using rendition %s" % name)
            return rendition["url"], title
    return None, "no usable rendition"


def download(url, path):
    """Stream a URL to a file. Returns (ok, message).

    Streamed in chunks rather than held in memory: even a 50 KB GIF is a
    quarter of the free heap on this board, and the renditions are not
    all as small as they claim.
    """
    try:
        r = _session.get(url, timeout=HTTP_TIMEOUT)
    except Exception as exc:
        return False, "download failed: %s" % exc

    try:
        if r.status_code != 200:
            return False, "HTTP %d" % r.status_code
        total = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    return False, "gif too big (>%dk)" % (MAX_BYTES // 1024)
                f.write(chunk)
    except Exception as exc:
        return False, "write failed: %s" % exc
    finally:
        r.close()

    print("GifPlayer: downloaded %d bytes" % total)
    return True, "%d bytes" % total


def fetch_giphy(tag, slot):
    """Whole GIPHY path: key -> wifi -> writable fs -> download."""
    if not GIPHY_API_KEY:
        show_status("no API key", "set GIPHY_API_KEY", "in settings.toml",
                    color=0xFF6060)
        return None
    if not connect_wifi():
        return None

    if tag == TRENDING:
        show_status("asking giphy...", "trending #%d" % (slot % TRENDING_TOP + 1))
    else:
        show_status("asking giphy...", tag)
    url, info = giphy_pick(tag, slot)
    if url is None:
        show_status("giphy error", info, color=0xFF6060)
        return None

    if not make_writable():
        show_status("USB has the disk", "eject CIRCUITPY or", "run on battery",
                    color=0xFF6060)
        return None

    show_status("downloading...", info)
    ensure_dir(LOCAL_DIR)
    ok, msg = download(url, CACHE_PATH)
    make_readonly()
    if not ok:
        show_status("download failed", msg, color=0xFF6060)
        return None

    gc.collect()
    return CACHE_PATH


# ==================================================================
# Player
# ==================================================================
def poll():
    """Return an action name if a switch was just pressed, else None."""
    global sw1_prev, sw2_prev, sw3_prev
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    act = None
    if (not v1) and sw1_prev:
        act = "next"
    elif (not v2) and sw2_prev:
        act = "tag"
    elif (not v3) and sw3_prev:
        act = "source"
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3
    return act


def play(path, credit):
    """Play one GIF until a button is pressed. Returns the action.

    The GIF is centred, and a taller-than-screen one is centre-cropped by
    giving the TileGrid a negative y -- displayio clips it for us.
    """
    if gifio is None:
        show_status("no gifio", "build lacks the", "gifio module",
                    color=0xFF6060)
        time.sleep(3)
        return "next"

    gc.collect()
    try:
        gif = gifio.OnDiskGif(path)
    except Exception as exc:
        # Too wide (>320), out of memory, or simply not a GIF.
        show_status("cannot play", path.split("/")[-1], str(exc),
                    color=0xFF6060)
        time.sleep(3)
        return "next"

    print("GifPlayer: %s %dx%d, %d frames" %
          (path, gif.width, gif.height, gif.frame_count))

    action = "next"
    try:
        group = displayio.Group()
        group.append(displayio.TileGrid(
            gif.bitmap,
            pixel_shader=displayio.ColorConverter(
                input_colorspace=displayio.Colorspace.RGB565_SWAPPED),
            x=(VW - gif.width) // 2,
            y=(VH - gif.height) // 2,
        ))
        # GIPHY's terms want their mark visible when you use their API.
        if credit:
            mark = label.Label(terminalio.FONT, text=credit, color=0xFFFFFF,
                               background_color=0x000000)
            mark.anchor_point = (0.5, 1.0)
            mark.anchored_position = (VW // 2, VH - 2)
            group.append(mark)

        display.root_group = group
        leds((0, 0, 0))

        # Measure the decode cost once and subtract it from the delay,
        # or every frame runs late by however long decoding took.
        start = time.monotonic()
        delay = gif.next_frame()
        overhead = time.monotonic() - start
        display.refresh()

        while True:
            wait = delay - overhead
            deadline = time.monotonic() + (wait if wait > 0.0 else 0.0)
            while True:
                act = poll()
                if act:
                    return act
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.005)
            delay = gif.next_frame()
            display.refresh()
    finally:
        # Frame buffers are the biggest allocation this sample makes;
        # the next GIF cannot be opened until this one lets go.
        gif.deinit()
        del gif
        gc.collect()
        display.root_group = status_group
    return action


# ==================================================================
# Main
# ==================================================================
sw1_prev = sw2_prev = sw3_prev = True

source = "local"          # "local" or "giphy"
tag_idx = 0
trend_slot = 0            # which of the trending top N we are on
local_idx = 0

show_status("starting...", "")
bl.value = True
leds((0, 20, 40))

if gifio is None:
    show_status("no gifio module", "this build cannot", "decode GIFs",
                color=0xFF6060)
    while True:
        time.sleep(1)

# Start wherever there is something to play. A badge with no /gifs/
# folder and no credentials should say so rather than sit blank.
local_gifs = list_local_gifs()
if not local_gifs and GIPHY_API_KEY:
    source = "giphy"

while True:
    if source == "giphy":
        leds((20, 0, 30))
        tag = TAGS[tag_idx]
        path = fetch_giphy(tag, trend_slot)
        if tag == TRENDING:
            credit = "GIPHY TRENDING %d" % (trend_slot % TRENDING_TOP + 1)
        else:
            credit = "GIPHY  #%s" % tag.replace(" ", "")
        if path is None:
            # Give the message time to be read, then let a button out.
            deadline = time.monotonic() + 4.0
            act = None
            while time.monotonic() < deadline and act is None:
                act = poll()
                time.sleep(0.02)
            if act == "source":
                source = "local"
            elif act == "tag":
                tag_idx = (tag_idx + 1) % len(TAGS)
            elif act is None and not list_local_gifs():
                pass                  # nothing else to fall back to
            continue
    else:
        local_gifs = list_local_gifs()
        if not local_gifs:
            show_status("no gifs", "put .gif files in", "/gifs/ on the badge",
                        color=0xFF6060)
            deadline = time.monotonic() + 4.0
            act = None
            while time.monotonic() < deadline and act is None:
                act = poll()
                time.sleep(0.02)
            if act == "source":
                source = "giphy"
            continue
        local_idx %= len(local_gifs)
        path = local_gifs[local_idx]
        credit = ""

    action = play(path, credit)

    if action == "next":
        if source == "local":
            local_idx += 1
        elif TAGS[tag_idx] == TRENDING:
            trend_slot += 1       # walk the top N instead of re-rolling
    elif action == "tag":
        tag_idx = (tag_idx + 1) % len(TAGS)
        if source == "local":
            source = "giphy"          # tags only mean something on GIPHY
    elif action == "source":
        source = "giphy" if source == "local" else "local"
        print("GifPlayer: source =", source)
