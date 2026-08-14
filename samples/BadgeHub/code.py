"""
BadgeHub -- Conference badge connected to a server
===================================================
Connects to a server over HTTP and displays broadcasts, runs light
commands, lets you vote in polls, and shows your mood. Works with the
badge-hub server in this repo.

Setup
-----
1. Put WiFi credentials in settings.toml:
   WIFI_SSID = "your-wifi"
   WIFI_PASSWORD = "your-password"

2. Set the server URL below (use https:// if behind ingress):
   SERVER_URL = "https://badge.sapslaj.cloud"

3. Set your name:
   MY_NAME = "YOUR NAME"

4. Save and the badge connects automatically.

Controls
--------
  SW1 (IO1)   -- cycle mood   (happy / excited / tired / hungry / cool)
  SW2 (IO2)   -- vote in active poll (cycles through options, press to vote)
  SW3 (IO43)  -- toggle between hub view and clock view

The badge checks in with the server on boot, then polls /api/state every
5 seconds for updates (broadcasts, light commands, poll changes, room mood).

OTA updates
-----------
Every 60 seconds BadgeHub also asks the server for a manifest covering
/samples/, /lib/, /mods/, and /tools/ (see server/main.go). Each top-level
entry in those directories -- a sample folder, a lib package, a mod, a
tool script -- is hashed on its own, so only what actually changed gets
pulled. Anything whose hash
differs from what's already on the badge is downloaded straight onto the
CIRCUITPY drive, and BadgeHub reboots to pick it up.

Like GifPlayer's GIPHY mode, this needs write access to the badge's own
filesystem, which CircuitPython only grants when the host computer isn't
holding it (i.e. running on battery, or with CIRCUITPY unmounted/ejected).
Plugged into a computer for development, updates are simply skipped with a
message on the serial console -- nothing on screen changes.
"""

import os
import time
import math
import json
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
import storage
import supervisor
import adafruit_requests
import adafruit_st7735r
from adafruit_display_text import label


# ==============================================================
#   Configuration
# ==============================================================

WIFI_SSID = os.getenv("WIFI_SSID", "your-wifi-name")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "your-wifi-password")

SERVER_URL = "https://badge.sapslaj.cloud"

MY_NAME = os.getenv("FIRST_NAME", "YOUR") + " " + os.getenv("LAST_NAME", "NAME")

OTA_KINDS = {
    "samples": "/samples",
    "lib": "/lib",
    "mods": "/mods",
    "tools": "/tools",
}
OTA_STATE_PATH = "/samples/.ota_state.json"
OTA_CHECK_INTERVAL = 60.0
# ==============================================================


# ------------------------------------------------------------------
# Hardware setup
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

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
# Networking
# ------------------------------------------------------------------
_session = None
_badge_id = None


def get_badge_id():
    """Use the ESP32's MAC address as a unique badge ID."""
    global _badge_id
    if _badge_id is None:
        mac = wifi.radio.mac_address
        _badge_id = "".join("%02x" % b for b in mac)
    return _badge_id


def http():
    global _session
    if _session is None:
        pool = socketpool.SocketPool(wifi.radio)
        _session = adafruit_requests.Session(pool, ssl.create_default_context())
    return _session


def connect_wifi():
    print("Connecting to WiFi:", WIFI_SSID)
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    print("  IP =", wifi.radio.ipv4_address)


def api_get(path):
    url = SERVER_URL + path
    r = http().get(url)
    try:
        data = r.json()
    finally:
        r.close()
    return data


def api_post(path, body):
    url = SERVER_URL + path
    r = http().post(url, json=body)
    try:
        data = r.json()
    finally:
        r.close()
    return data


def send_telemetry(message):
    """Log a message to the server, tagged with this badge's id and name.

    A debug backchannel for exactly the situation this badge is usually
    in when something is wrong: on battery, no serial console, and the
    display already busy showing something else. Best-effort -- a failed
    telemetry send must never be the thing that takes the badge down.
    """
    if not wifi.radio.ipv4_address:
        return
    try:
        api_post("/api/telemetry", {
            "id": get_badge_id(),
            "first_name": os.getenv("FIRST_NAME", ""),
            "last_name": os.getenv("LAST_NAME", ""),
            "message": message[:200],
        })
    except Exception as exc:
        print("BadgeHub: telemetry send failed:", exc)


# ------------------------------------------------------------------
# OTA updates (samples, lib, mods)
# ------------------------------------------------------------------
def make_writable():
    """Try to get write access to the badge's own filesystem.

    Same tradeoff GifPlayer's GIPHY mode makes: CircuitPython hands write
    access to exactly one of the badge and the host computer, so this
    fails (harmlessly) whenever a computer has CIRCUITPY mounted.
    """
    try:
        storage.remount("/", readonly=False)
        return True
    except Exception as exc:
        print("BadgeHub: filesystem is read-only, skipping OTA update:", exc)
        return False


def make_readonly():
    try:
        storage.remount("/", readonly=True)
    except Exception:
        pass


def ensure_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass  # already there, or not writable


def ensure_dirs_for(file_path):
    """Create every directory component of a file path that is missing.
    Samples are mostly flat, but GifPlayer ships a tools/ subfolder."""
    parts = file_path.split("/")[:-1]
    cur = ""
    for part in parts:
        if not part:
            continue
        cur += "/" + part
        ensure_dir(cur)


def load_ota_state():
    try:
        with open(OTA_STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_ota_state(state):
    try:
        with open(OTA_STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception as exc:
        print("BadgeHub: could not save OTA state:", exc)


def ota_download_file(kind, rel_path, dest_path):
    url = SERVER_URL + "/api/ota/file?kind=" + kind + "&path=" + rel_path
    r = http().get(url)
    try:
        if r.status_code != 200:
            print("BadgeHub: OTA fetch failed:", kind, rel_path, r.status_code)
            return False
        ensure_dirs_for(dest_path)
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
        return True
    except Exception as exc:
        print("BadgeHub: OTA write failed:", kind, rel_path, exc)
        return False
    finally:
        r.close()


def apply_unit_update(kind, info):
    """Download every file listed for one unit (a sample folder, a lib
    package, a mod). Every file's path already comes back from the server
    relative to the kind's root, so ensure_dirs_for handles nesting on its
    own. Only succeeds (and is only recorded as applied) if every file
    lands cleanly -- a half-written unit is worse than a stale one."""
    kind_dir = OTA_KINDS[kind]
    for f in info["files"]:
        dest = kind_dir + "/" + f["path"]
        if not ota_download_file(kind, f["path"], dest):
            return False
    return True


def check_ota_updates():
    """Compare the server's manifest -- samples, lib, mods, tools -- against
    what's on the badge and pull down anything that changed. Returns True
    if at least one unit was updated.

    Sends one telemetry line per call (see send_telemetry) so this whole
    flow -- fetch, diff, write-access, apply -- can be watched from the
    admin page while the badge runs untethered with no serial console.
    """
    try:
        manifest = api_get("/api/ota/manifest")
    except Exception as exc:
        print("BadgeHub: OTA manifest fetch failed:", exc)
        send_telemetry("ota: manifest fetch failed: %s" % exc)
        return False

    kinds = manifest.get("kinds", {})
    total_units = sum(len(k.get("units", {})) for k in kinds.values())
    state = load_ota_state()
    pending = []
    for kind in OTA_KINDS:
        kind_state = state.setdefault(kind, {})
        units = kinds.get(kind, {}).get("units", {})
        for name, info in units.items():
            if kind_state.get(name) != info.get("hash"):
                pending.append((kind, name, info))

    if not pending:
        send_telemetry("ota: up to date (%d units on server)" % total_units)
        return False

    send_telemetry("ota: %d/%d unit(s) pending: %s" % (
        len(pending), total_units,
        ", ".join("%s/%s" % (k, n) for k, n, _ in pending[:8])))

    if not make_writable():
        send_telemetry("ota: filesystem read-only (USB tethered?), cannot apply")
        return False

    updated = False
    applied = []
    failed = []
    try:
        for kind, name, info in pending:
            print("BadgeHub: OTA updating", kind, name)
            if apply_unit_update(kind, info):
                state[kind][name] = info["hash"]
                updated = True
                applied.append("%s/%s" % (kind, name))
            else:
                print("BadgeHub: OTA update incomplete, will retry:", kind, name)
                failed.append("%s/%s" % (kind, name))
        if updated:
            save_ota_state(state)
    finally:
        make_readonly()

    send_telemetry("ota: applied %d, failed %d%s" % (
        len(applied), len(failed),
        (" (" + ", ".join(failed[:8]) + ")") if failed else ""))

    return updated


# ------------------------------------------------------------------
# Color helpers
# ------------------------------------------------------------------
def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def hsv_to_rgb(h, s, v):
    h = h - int(h)
    if h < 0: h += 1.0
    if s == 0.0:
        c = int(v * 255)
        return (c, c, c)
    h6 = h * 6.0
    i = int(h6) % 6
    f = h6 - int(h6)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    if i == 0: return (int(v*255), int(t*255), int(p*255))
    if i == 1: return (int(q*255), int(v*255), int(p*255))
    if i == 2: return (int(p*255), int(v*255), int(t*255))
    if i == 3: return (int(p*255), int(q*255), int(v*255))
    if i == 4: return (int(t*255), int(p*255), int(v*255))
    return         (int(v*255), int(p*255), int(q*255))


# ------------------------------------------------------------------
# Moods
# ------------------------------------------------------------------
MOODS = (
    ("happy",   (0, 255, 0)),
    ("excited", (255, 136, 0)),
    ("tired",   (136, 136, 136)),
    ("hungry",  (255, 68, 68)),
    ("cool",    (0, 170, 255)),
)
mood_idx = 0


# ------------------------------------------------------------------
# Light pattern renderer
# ------------------------------------------------------------------
def render_lights(pattern, color_hex, t):
    """Set the 5 NeoPixels based on the server's light command."""
    rgb = hex_to_rgb(color_hex) if color_hex else (0, 0, 0)

    if pattern == "off":
        pixels.fill((0, 0, 0))

    elif pattern == "solid":
        pixels.fill(rgb)

    elif pattern == "rainbow":
        for i in range(5):
            pixels[i] = hsv_to_rgb((i / 5.0 + t * 0.15) % 1.0, 1.0, 1.0)

    elif pattern == "chase":
        pos = (t * 3.0) % 5.0
        for i in range(5):
            d = min(abs(i - pos), abs(i - pos - 5), abs(i - pos + 5))
            b = max(0.0, 1.0 - d * 0.55)
            pixels[i] = tuple(int(c * b * b) for c in rgb)

    elif pattern == "breathe":
        b = 0.15 + 0.85 * (0.5 + 0.5 * math.sin(t * 2.2))
        pixels.fill(tuple(int(c * b) for c in rgb))

    elif pattern == "strobe":
        on = int(t * 5.0) % 2 == 0
        pixels.fill(rgb if on else (0, 0, 0))

    elif pattern == "wave":
        for i in range(5):
            b = 0.15 + 0.85 * (0.5 + 0.5 * math.sin(t * 3.0 - i * 0.6))
            pixels[i] = tuple(int(c * b) for c in rgb)

    elif pattern == "pulse":
        period = 1.2
        tp = (t % period) / period
        if   tp < 0.08: b = tp / 0.08
        elif tp < 0.20: b = 1.0 - (tp - 0.08) / 0.12 * 0.7
        elif tp < 0.28: b = 0.3 + (tp - 0.20) / 0.08 * 0.7
        elif tp < 0.50: b = 1.0 - (tp - 0.28) / 0.22
        else:           b = 0.0
        pixels.fill(tuple(int(c * b) for c in rgb))

    else:
        pixels.fill((0, 0, 0))

    pixels.show()


# ------------------------------------------------------------------
# Display scenes
# ------------------------------------------------------------------
scene = displayio.Group()

bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1); bg_pal[0] = 0x000010
scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

# Title
title_lbl = label.Label(terminalio.FONT, text="BADGE HUB", scale=2, color=0x00FFFF)
title_lbl.anchor_point = (0.5, 0.5)
title_lbl.anchored_position = (64, 12)
scene.append(title_lbl)

# Connection status
status_lbl = label.Label(terminalio.FONT, text="connecting...", color=0xFFFF00)
status_lbl.anchor_point = (0.5, 0.5)
status_lbl.anchored_position = (64, 28)
scene.append(status_lbl)

# Broadcast message (scrolling area)
broadcast_lbl = label.Label(terminalio.FONT, text="", scale=2, color=0xFFFFFF)
broadcast_lbl.anchor_point = (0.5, 0.5)
broadcast_lbl.anchored_position = (64, 56)
scene.append(broadcast_lbl)

# Room mood
mood_lbl = label.Label(terminalio.FONT, text="", color=0xFFA030)
mood_lbl.anchor_point = (0.5, 0.5)
mood_lbl.anchored_position = (64, 80)
scene.append(mood_lbl)

# Poll display
poll_q_lbl = label.Label(terminalio.FONT, text="", color=0x60FF60)
poll_q_lbl.anchor_point = (0.5, 0.5)
poll_q_lbl.anchored_position = (64, 100)
scene.append(poll_q_lbl)

poll_opts_lbl = label.Label(terminalio.FONT, text="", color=0xA0A0FF)
poll_opts_lbl.anchor_point = (0.5, 0.5)
poll_opts_lbl.anchored_position = (64, 116)
scene.append(poll_opts_lbl)

# My mood indicator
my_mood_lbl = label.Label(terminalio.FONT, text="", color=0x808080)
my_mood_lbl.anchor_point = (0.5, 0.5)
my_mood_lbl.anchored_position = (64, 134)
scene.append(my_mood_lbl)

# Button hints
hint_lbl = label.Label(terminalio.FONT, text="S1:mood S2:vote S3:view", color=0x606060)
hint_lbl.anchor_point = (0.5, 0.5)
hint_lbl.anchored_position = (64, 152)
scene.append(hint_lbl)

display.root_group = scene


# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------
last_state_fetch = 0.0
STATE_INTERVAL = 1.0

current_state = {
    "broadcast": {"text": "", "color": "#ffffff"},
    "lights": {"pattern": "off", "color": "#000000"},
    "poll": {"active": False, "question": "", "options": [], "tally": {}},
    "mood": {},
    "online": 0,
}

poll_vote_idx = 0
view_mode = 0  # 0 = hub, 1 = clock


def update_display(state):
    """Update the TFT with the latest state from the server."""
    # Broadcast
    bc = state["broadcast"]
    if bc["text"]:
        broadcast_lbl.text = bc["text"][:20]
        try:
            r, g, b = hex_to_rgb(bc["color"])
            broadcast_lbl.color = (r << 16) | (g << 8) | b
        except Exception:
            broadcast_lbl.color = 0xFFFFFF
    else:
        broadcast_lbl.text = ""

    # Room mood summary
    mood_parts = []
    for mood, count in state["mood"].items():
        mood_parts.append("%s:%d" % (mood, count))
    mood_lbl.text = " ".join(mood_parts) if mood_parts else ""

    # Poll
    poll = state["poll"]
    if poll["active"]:
        poll_q_lbl.text = poll["question"][:20]
        tally_parts = []
        for opt in poll["options"]:
            v = poll["tally"].get(opt, 0)
            tally_parts.append("%s(%d)" % (opt[:8], v))
        poll_opts_lbl.text = " ".join(tally_parts)
    else:
        poll_q_lbl.text = ""
        poll_opts_lbl.text = ""

    # My mood
    mood_name, mood_rgb = MOODS[mood_idx]
    my_mood_lbl.text = "me: %s" % mood_name
    r, g, b = mood_rgb
    my_mood_lbl.color = (r << 16) | (g << 8) | b

    # Online count in status
    status_lbl.text = "online: %d" % state["online"]
    status_lbl.color = 0x00FF00

    display.refresh()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
display.refresh()
bl.value = True

# Connect WiFi
status_lbl.text = "wifi..."
display.refresh()
try:
    connect_wifi()
except Exception as e:
    status_lbl.text = "wifi fail!"
    status_lbl.color = 0xFF0000
    display.refresh()
    print("WiFi error:", e)
    time.sleep(5)
    # keep going -- badge still works offline for LED patterns

# Check in with server
if wifi.radio.ipv4_address:
    status_lbl.text = "checking in..."
    display.refresh()
    try:
        api_post("/api/checkin", {"id": get_badge_id(), "name": MY_NAME})
        api_post("/api/mood", {"id": get_badge_id(), "mood": MOODS[mood_idx][0]})
        status_lbl.text = "connected!"
        status_lbl.color = 0x00FF00
    except Exception as e:
        status_lbl.text = "server fail"
        status_lbl.color = 0xFF8800
        print("Checkin error:", e)
    display.refresh()

# Fetch initial state
if wifi.radio.ipv4_address:
    try:
        current_state = api_get("/api/state?id=" + get_badge_id())
        update_display(current_state)
    except Exception as e:
        print("State fetch error:", e)

# Check for OTA updates right away, so a badge that boots with something
# stale on disk gets fixed before anyone picks it from the menu.
if wifi.radio.ipv4_address:
    status_lbl.text = "checking updates..."
    display.refresh()
    try:
        if check_ota_updates():
            status_lbl.text = "updated! restarting"
            status_lbl.color = 0x00FF00
            display.refresh()
            time.sleep(2)
            supervisor.reload()
    except Exception as e:
        print("BadgeHub: OTA check failed:", e)
    update_display(current_state)

last_state_fetch = time.monotonic()
last_ota_check = time.monotonic()

# Main loop
sw1_prev = True; sw2_prev = True; sw3_prev = True
last_poll_vote_time = 0.0
POLL_VOTE_COOLDOWN = 0.3

while True:
    now = time.monotonic()
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    pressed_sw1 = (not v1) and sw1_prev
    pressed_sw2 = (not v2) and sw2_prev
    pressed_sw3 = (not v3) and sw3_prev
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    # SW1: cycle mood
    if pressed_sw1:
        mood_idx = (mood_idx + 1) % len(MOODS)
        mood_name = MOODS[mood_idx][0]
        print("mood:", mood_name)
        if wifi.radio.ipv4_address:
            try:
                api_post("/api/mood", {"id": get_badge_id(), "mood": mood_name})
            except Exception:
                pass
        update_display(current_state)

    # SW2: vote in poll
    if pressed_sw2 and current_state["poll"]["active"]:
        opts = current_state["poll"]["options"]
        if opts:
            poll_vote_idx = (poll_vote_idx + 1) % len(opts)
            if now - last_poll_vote_time > POLL_VOTE_COOLDOWN:
                choice = opts[poll_vote_idx]
                print("vote:", choice)
                if wifi.radio.ipv4_address:
                    try:
                        api_post("/api/vote", {"id": get_badge_id(), "option": choice})
                    except Exception:
                        pass
                last_poll_vote_time = now

    # SW3: toggle view mode
    if pressed_sw3:
        view_mode = 1 - view_mode
        if view_mode == 1:
            # clock mode
            title_lbl.text = "CLOCK"
            broadcast_lbl.text = ""
            mood_lbl.text = ""
            poll_q_lbl.text = ""
            poll_opts_lbl.text = ""
            hint_lbl.text = "S3: back to hub"
        else:
            title_lbl.text = "BADGE HUB"
            hint_lbl.text = "S1:mood S2:vote S3:view"
            update_display(current_state)
        display.refresh()

    # Fetch state periodically
    if wifi.radio.ipv4_address and (now - last_state_fetch) > STATE_INTERVAL:
        try:
            current_state = api_get("/api/state?id=" + get_badge_id())
            if view_mode == 0:
                update_display(current_state)
        except Exception as e:
            print("State fetch error:", e)
        last_state_fetch = now

    # Check for OTA updates periodically
    if wifi.radio.ipv4_address and (now - last_ota_check) > OTA_CHECK_INTERVAL:
        last_ota_check = now
        try:
            if check_ota_updates():
                status_lbl.text = "updated! restarting"
                status_lbl.color = 0x00FF00
                display.refresh()
                time.sleep(2)
                supervisor.reload()
        except Exception as e:
            print("BadgeHub: OTA check failed:", e)

    # Render lights
    lights = current_state["lights"]
    render_lights(lights["pattern"], lights["color"], now)

    # Clock mode display
    if view_mode == 1:
        struct = time.localtime()
        clock_str = "%02d:%02d" % (struct.tm_hour, struct.tm_min)
        broadcast_lbl.text = clock_str
        broadcast_lbl.color = 0x00FFFF
        display.refresh()

    time.sleep(0.02)
