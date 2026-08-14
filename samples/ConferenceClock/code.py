"""
code.py -- Conference Clock
====================================================================
A live NTP-synced clock with a configurable timezone and a countdown
to the next session on the conference schedule. WiFi credentials
come from settings.toml; the clock syncs against pool.ntp.org using a
~30-line hand-written NTP client over UDP (no extra library needed)
and re-syncs hourly. The 5 NeoPixels form a seconds progress bar.

Time zones
----------
NTP returns UTC. Set TZ_OFFSET_HOURS below to your local offset from
UTC (negative west of Greenwich). The default is -5 (US Eastern
Standard Time); use -4 for Eastern Daylight Time during DST.

Controls
--------
  SW3 (IO43)  -- manual re-sync (also retries after a network error)
"""

import os
import time
import board
import busio
import digitalio
import displayio
import fourwire
import neopixel
import wifi
import socketpool
import terminalio
import adafruit_st7735r
from adafruit_display_text import label

# ==============================================================
#  Configuration
# ==============================================================
WIFI_SSID = os.getenv("WIFI_SSID", "your-wifi-name")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "your-wifi-password")

TZ_OFFSET_HOURS = -4     # UTC offset; -5 = EST, -4 = EDT

# Conference dates: Day 1 = Aug 14 2026, Day 2 = Aug 15 2026.
CONF_YEAR = 2026
CONF_MONTH = 8
CONF_DAYS = [14, 15]   # index 0 = day 1, index 1 = day 2

# Editable schedule: "day" (1 or 2), 24-hour "HH:MM" start, title, duration (min).
# Times are LOCAL.  Titles shown on-screen are truncated to 20 chars by the
# renderer.
SCHEDULE = [
    # --- Day 1 (Aug 14): Morning ---
    {"day": 1, "start": "09:00", "title": "Kerstiens: Postgres", "dur": 60},
    {"day": 1, "start": "10:00", "title": "Presley: Better Types", "dur": 30},
    {"day": 1, "start": "10:30", "title": "Noe: OpenLDAP", "dur": 15},
    {"day": 1, "start": "10:45", "title": "Sullivan: Elixir & AI", "dur": 30},
    {"day": 1, "start": "11:15", "title": "Danelz: Protobuf", "dur": 15},
    {"day": 1, "start": "11:30", "title": "Kulkarni: Batch Obs", "dur": 30},
    {"day": 1, "start": "12:00", "title": "Davies: Codegen", "dur": 90},
    # --- Day 1 (Aug 14): Afternoon ---
    {"day": 1, "start": "13:30", "title": "Teitel: Computer Vis", "dur": 30},
    {"day": 1, "start": "14:00", "title": "Augustine: KEDA", "dur": 15},
    {"day": 1, "start": "14:15", "title": "Poston: Malware", "dur": 30},
    {"day": 1, "start": "14:45", "title": "BREAK", "dur": 15},
    {"day": 1, "start": "15:00", "title": "Anderson: Vibe Coding", "dur": 30},
    {"day": 1, "start": "15:30", "title": "Rawlinson: Security", "dur": 15},
    {"day": 1, "start": "15:45", "title": "Pham: Robot Dog APIs", "dur": 60},
    # --- Day 2 (Aug 15): Morning ---
    {"day": 2, "start": "09:00", "title": "Haynes: Clef Lang", "dur": 60},
    {"day": 2, "start": "10:00", "title": "Mackey: Mutator Tests", "dur": 30},
    {"day": 2, "start": "10:30", "title": "Overcash: Keycloak", "dur": 15},
    {"day": 2, "start": "10:45", "title": "Jarrett: Ada 2026", "dur": 30},
    {"day": 2, "start": "11:15", "title": "Braun: AI Agent Tool", "dur": 15},
    {"day": 2, "start": "11:30", "title": "Heyman: COBOL Round 2", "dur": 30},
    {"day": 2, "start": "12:00", "title": "Gotimer: Containers", "dur": 90},
    # --- Day 2 (Aug 15): Afternoon ---
    {"day": 2, "start": "13:30", "title": "Benfield: Micro VMs", "dur": 30},
    {"day": 2, "start": "14:00", "title": "Cone: YAML Moat", "dur": 30},
    {"day": 2, "start": "14:30", "title": "Ballanco: Julia", "dur": 30},
    {"day": 2, "start": "15:00", "title": "Willis: 3 Mentors", "dur": 15},
    {"day": 2, "start": "15:15", "title": "Rodriguez: C# w/ C#", "dur": 30},
    {"day": 2, "start": "15:45", "title": "Grainger: Wormhole Vec", "dur": 60},
]
# ==============================================================


# ------------------------------------------------------------------
# Hardware
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.3, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

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

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# ------------------------------------------------------------------
# Scenes: clock view + error view
# ------------------------------------------------------------------
clock_scene = displayio.Group()
bg = displayio.Bitmap(128, 160, 1)
bp = displayio.Palette(1); bp[0] = 0x000814
clock_scene.append(displayio.TileGrid(bg, pixel_shader=bp, x=0, y=0))

title_lbl = label.Label(terminalio.FONT, text="CONFERENCE CLOCK", color=0x00FFCC, x=14, y=6)
clock_lbl = label.Label(terminalio.FONT, text="--:--:--", color=0xFFFFFF, scale=2, x=16, y=34)
date_lbl = label.Label(terminalio.FONT, text="", color=0x80C0FF, x=8, y=62)
next_lbl = label.Label(terminalio.FONT, text="NEXT", color=0x606060, x=4, y=84)
sess_lbl = label.Label(terminalio.FONT, text="", color=0xFFFF66, scale=1, x=4, y=98)
cd_lbl = label.Label(terminalio.FONT, text="", color=0x66FF66, scale=2, x=16, y=118)
status_lbl = label.Label(terminalio.FONT, text="", color=0x404040, x=4, y=152)
for l in (title_lbl, clock_lbl, date_lbl, next_lbl, sess_lbl, cd_lbl, status_lbl):
    clock_scene.append(l)

err_scene = displayio.Group()
ebg = displayio.Bitmap(128, 160, 1)
ep = displayio.Palette(1); ep[0] = 0x400000
err_scene.append(displayio.TileGrid(ebg, pixel_shader=ep, x=0, y=0))
err_title = label.Label(terminalio.FONT, text="SYNC FAILED", scale=2, color=0xFFFF00, x=10, y=12)
err_lines = []
for i in range(8):
    lb = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=8, y=42 + i * 12)
    err_lines.append(lb); err_scene.append(lb)
err_foot = label.Label(terminalio.FONT, text="SW3 to retry", color=0xFFC000, x=8, y=150)
err_scene.append(err_title); err_scene.append(err_foot)

display.root_group = clock_scene


def show_error(title, lines):
    err_title.text = title
    for i, lb in enumerate(err_lines):
        lb.text = lines[i] if i < len(lines) else ""
    pixels.fill((60, 0, 0)); pixels.show()
    display.root_group = err_scene
    display.refresh()
    print("!", title, lines)


def show_clock():
    display.root_group = clock_scene


# ------------------------------------------------------------------
# Networking: WiFi + a tiny hand-rolled NTP client over UDP
# ------------------------------------------------------------------
def connect_wifi():
    status_lbl.text = "wifi: connecting..."
    status_lbl.color = 0xFFFF00
    display.refresh()
    pixels.fill((30, 30, 0)); pixels.show()
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    status_lbl.text = "wifi: %s" % wifi.radio.ipv4_address
    status_lbl.color = 0x00A000
    display.refresh()
    print("WiFi IP:", wifi.radio.ipv4_address)


def ntp_unix():
    """Return current unix time from pool.ntp.org (raises on failure)."""
    pool = socketpool.SocketPool(wifi.radio)
    s = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
    try:
        s.settimeout(2)
        pkt = bytearray(48)
        pkt[0] = 0x1B
        addr = pool.getaddrinfo("pool.ntp.org", 123)[0][4]
        s.sendto(pkt, addr)
        data = bytearray(48)
        n = s.recv_into(data)
        if n < 48:
            raise OSError("short NTP reply")
        secs = (data[40] << 24) | (data[41] << 16) | (data[42] << 8) | data[43]
        return secs - 2208988800   # 1900 epoch -> 1970 epoch
    finally:
        s.close()


# monotonic <-> unix offset, set at sync time
unix_at_sync = None
mono_at_sync = 0.0


def now_unix():
    return unix_at_sync + (time.monotonic() - mono_at_sync)


def sync():
    """Connect + NTP. Raises on failure."""
    if not wifi.radio.connected:
        connect_wifi()
    global unix_at_sync, mono_at_sync
    status_lbl.text = "ntp: syncing..."
    status_lbl.color = 0xFFFF00
    display.refresh()
    u = ntp_unix()
    unix_at_sync = u
    mono_at_sync = time.monotonic()
    pixels.fill((0, 30, 0)); pixels.show()
    print("NTP sync: unix =", u, "->", time.localtime(u + TZ_OFFSET_HOURS * 3600))


def wifi_err(e):
    return ("WIFI ERROR",
            ["", '"%s"' % WIFI_SSID, "", str(e)[:20], "", "Check WIFI_SSID /",
             "WIFI_PASSWORD", "in settings.toml"])


def ntp_err(e):
    return ("NTP ERROR",
            ["", "Reached WiFi but", "NTP sync failed:", "", str(e)[:20], "",
             "Check DNS /", "outbound UDP 123"])


# ------------------------------------------------------------------
# Schedule logic
# ------------------------------------------------------------------
def session_unix(entry):
    """Absolute unix timestamp for a session's local start time."""
    h, m = entry["start"].split(":")
    day = CONF_DAYS[entry["day"] - 1]
    return time.mktime((CONF_YEAR, CONF_MONTH, day, int(h), int(m), 0, 0, 0, 0))


def next_session(now):
    """Return (entry, secs_until_start, secs_until_end, is_now).
    If the conference is over, entry is None."""
    items = sorted(SCHEDULE, key=session_unix)
    for e in items:
        start = session_unix(e)
        end = start + e["dur"] * 60
        if start <= now < end:
            return (e, start - now, end - now, True)   # happening now
    for e in items:
        start = session_unix(e)
        if start > now:
            return (e, start - now, 0, False)
    # conference is over
    return (None, 0, 0, False)


def fmt_countdown(sec):
    sec = int(sec)
    d = sec // 86400
    sec %= 86400
    h = sec // 3600
    m = (sec % 3600) // 60
    if d:
        return "in %dd %dh" % (d, h)
    if h:
        return "in %dh %dm" % (h, m)
    if m:
        return "in %dm" % m
    return "in %ds" % sec


# ------------------------------------------------------------------
# Render
# ------------------------------------------------------------------
def render_clock():
    u_raw = now_unix()                # UTC unix — for schedule comparison
    u = u_raw + TZ_OFFSET_HOURS * 3600  # local — for display
    st = time.localtime(u)
    clock_lbl.text = "%02d:%02d:%02d" % (st.tm_hour, st.tm_min, st.tm_sec)
    date_lbl.text = "%s  %s %d %d" % (WEEKDAYS[st.tm_wday], MONTHS[st.tm_mon - 1],
                                      st.tm_mday, st.tm_year)
    e, until_start, until_end, is_now = next_session(u)
    if e is None:
        next_lbl.text = "DONE"
        next_lbl.color = 0x606060
        sess_lbl.text = "Conference Over"
        cd_lbl.text = "thanks!"
        cd_lbl.color = 0x606060
    elif is_now:
        next_lbl.text = "NOW"
        next_lbl.color = 0xFF6644
        sess_lbl.text = e["title"][:20]
        cd_lbl.text = "%dm left" % max(0, until_end // 60)
        cd_lbl.color = 0xFF6644
    else:
        next_lbl.text = "NEXT"
        next_lbl.color = 0x606060
        sess_lbl.text = e["title"][:20]
        cd_lbl.text = fmt_countdown(until_start)
        cd_lbl.color = 0x66FF66
    # seconds -> 5-LED bar (each LED ~12s)
    n = min(5, st.tm_sec // 12 + 1)
    for i in range(5):
        pixels[i] = (0, 120, 200) if i < n else (0, 10, 20)
    pixels.show()
    display.refresh()


# ------------------------------------------------------------------
# Boot
# ------------------------------------------------------------------
title_lbl.text = "CONFERENCE CLOCK"
status_lbl.text = "starting..."
display.refresh()
bl.value = True

synced = False
try:
    sync()
    synced = True
except Exception as e:
    print("sync failed:", e)
    msg = str(e)
    if "auth" in msg.lower() or "password" in msg.lower() or "ssid" in msg.lower():
        show_error(*wifi_err(e))
    else:
        show_error(*ntp_err(e))

last_sync = time.monotonic()
last_render = 0.0
s3p = True

while True:
    now = time.monotonic()
    p3 = (not sw3.value) and s3p
    s3p = sw3.value

    if not synced and p3:
        try:
            sync(); synced = True
            show_clock()
        except Exception as e:
            show_error(*ntp_err(e))
        time.sleep(0.3)
        continue

    if synced:
        # re-sync hourly
        if now - last_sync > 3600:
            try:
                sync()
            except Exception as e:
                print("resync failed:", e)
                status_lbl.text = "resync failed"
                status_lbl.color = 0xFF4040
            last_sync = now
        # render ~4 fps
        if now - last_render > 0.25:
            render_clock()
            last_render = now
    time.sleep(0.05)
