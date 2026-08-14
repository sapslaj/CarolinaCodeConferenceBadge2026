"""
code.py -- Port Scanner (pocket tricorder)
====================================================================
A live TCP port scanner for the conference badge. It joins your WiFi,
works out the local /24 subnet from the badge's own IP, and probes a
handful of common ports on the first HOST_COUNT hosts -- drawing each
result into a live grid as it goes. Open ports light up green, closed
hosts show dim, and the cell being probed flashes yellow.

This is the ethical-hacking demo: it only touches the local subnet
you're already on (your own network), and uses short non-aggressive
timeouts. Great for "what's actually listening on my home network?"
walks at a conference.

Controls
--------
  SW1 (IO1)   -- scan the previous host octet window
  SW2 (IO2)   -- start a fresh scan
  SW3 (IO43)  -- scan the next host octet window
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
import bitmaptools
import terminalio
import adafruit_st7735r
from adafruit_display_text import label

# ==============================================================
#  Configuration
# ==============================================================
WIFI_SSID = os.getenv("WIFI_SSID", "your-wifi-name")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "your-wifi-password")

HOST_COUNT = 12          # how many hosts (.1 .. .N) to probe per window
PROBE_TIMEOUT = 0.12      # seconds per TCP connect
PORTS = [22, 23, 80, 443, 445, 3389, 8080]
# ==============================================================


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
# Grid layout
#   HUD top 18px (title + status). Host-index row at y=20. Matrix below.
#   port label column x=0..22, then HOST_COUNT cells of 8px from x=24.
# ------------------------------------------------------------------
HEX = "0123456789ABCDEF"
LABEL_X = 2
CELL_W = 8
CELL_X0 = 24
MATRIX_Y0 = 28
ROW_H = 17

# Palette: 0 bg, 1 open green, 2 closed dim, 3 scanning yellow, 4 gridline
pal = displayio.Palette(5)
pal[0] = 0x050A08
pal[1] = 0x00FF66
pal[2] = 0x222028
pal[3] = 0xFFFF44
pal[4] = 0x101418

scene = displayio.Group()
canvas = displayio.Bitmap(128, 160, 5)
scene.append(displayio.TileGrid(canvas, pixel_shader=pal, x=0, y=0))

title_lbl = label.Label(terminalio.FONT, text="PORT SCANNER", color=0x00FFCC, x=2, y=4)
status_lbl = label.Label(terminalio.FONT, text="booting...", color=0x808080, x=2, y=14)
scene.append(title_lbl); scene.append(status_lbl)

# host-index labels across the top of the matrix
host_lbls = []
for i in range(HOST_COUNT):
    lb = label.Label(terminalio.FONT, text=HEX[i + 1], color=0x404040,
                     x=CELL_X0 + i * CELL_W + 1, y=20)
    scene.append(lb); host_lbls.append(lb)

# port-row labels
port_lbls = []
for i, p in enumerate(PORTS):
    lb = label.Label(terminalio.FONT, text=str(p), color=0x606060,
                     x=LABEL_X, y=MATRIX_Y0 + i * ROW_H + 2)
    scene.append(lb); port_lbls.append(lb)

legend_lbl = label.Label(terminalio.FONT,
                        text="open  closed  scan", color=0x505050, x=6, y=156)
scene.append(legend_lbl)

display.root_group = scene

# results matrix: results[port_i][host_i] -> 0 unk,1 open,2 closed,3 scanning
results = [[0] * HOST_COUNT for _ in PORTS]


def draw_cell(pi, hi, state):
    x = CELL_X0 + hi * CELL_W
    y = MATRIX_Y0 + pi * ROW_H
    bitmaptools.fill_region(canvas, x, y, x + CELL_W, y + ROW_H - 2, state)
    display.refresh()


def draw_legend_swatch():
    # small colour swatches next to the legend text
    bitmaptools.fill_region(canvas, 2, 152, 6, 158, 1)
    bitmaptools.fill_region(canvas, 30, 152, 36, 158, 2)
    bitmaptools.fill_region(canvas, 70, 152, 76, 158, 3)
    display.refresh()


def clear_matrix():
    for pi in range(len(PORTS)):
        for hi in range(HOST_COUNT):
            results[pi][hi] = 0
            draw_cell(pi, hi, 0)


# ------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------
_subnet = None      # "192.168.1"
_window = 0         # first host octet offset (0 -> .1.. .12)
MAX_WINDOW = 254 - HOST_COUNT   # keep octet = window+1..+HOST_COUNT <= 254


def connect_wifi():
    status_lbl.text = "wifi: connecting..."
    status_lbl.color = 0xFFFF00
    display.refresh()
    pixels.fill((30, 30, 0)); pixels.show()
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    ip = str(wifi.radio.ipv4_address)
    parts = ip.split(".")
    global _subnet
    _subnet = ".".join(parts[:3])
    status_lbl.text = "wifi up  %s.0/24" % _subnet
    status_lbl.color = 0x00A000
    display.refresh()
    pixels.fill((0, 20, 0)); pixels.show()
    print("WiFi up, subnet", _subnet)


def probe(ip, port, pool):
    sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
    try:
        sock.settimeout(PROBE_TIMEOUT)
        sock.connect((ip, port))
        return True    # open
    except OSError:
        return False   # closed / filtered / timeout
    finally:
        sock.close()


def scan_window(pool):
    """Probe every (host, port) in the current window, live-updating the grid."""
    clear_matrix()
    base = _window
    for hi in range(HOST_COUNT):
        octet = base + hi + 1
        ip = "%s.%d" % (_subnet, octet)
        host_lbls[hi].text = HEX[octet] if octet < 16 else "?"
        host_lbls[hi].color = 0xAAAAAA
        for pi, port in enumerate(PORTS):
            results[pi][hi] = 3               # scanning
            draw_cell(pi, hi, 3)
            status_lbl.text = "%s:%d" % (ip, port)
            status_lbl.color = 0xFFFF44
            open_ = probe(ip, port, pool)
            results[pi][hi] = 1 if open_ else 2
            draw_cell(pi, hi, 1 if open_ else 2)
            # quick LED tally of open ports found so far
            opens = sum(1 for r in results for v in r if v == 1)
            n = min(5, opens)
            for k in range(5):
                pixels[k] = (0, 200, 80) if k < n else (0, 0, 0)
            pixels.show()
    status_lbl.text = "done. SW2 rescan"
    status_lbl.color = 0x00AA00
    display.refresh()


# ------------------------------------------------------------------
# Boot
# ------------------------------------------------------------------
draw_legend_swatch()
clear_matrix()
title_lbl.text = "PORT SCANNER"
display.refresh()
bl.value = True

pool = None
connected = False
err = None
try:
    connect_wifi()
    pool = socketpool.SocketPool(wifi.radio)
    connected = True
except Exception as e:
    err = e
    print("wifi failed:", e)

if connected:
    scan_window(pool)
else:
    status_lbl.text = "wifi failed"
    status_lbl.color = 0xFF4040
    display.refresh()
    pixels.fill((255, 0, 0)); pixels.show()

s1p = s2p = s3p = True

while True:
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    p1 = (not v1) and s1p
    p2 = (not v2) and s2p
    p3 = (not v3) and s3p
    s1p, s2p, s3p = v1, v2, v3

    if not connected:
        if p2:
            try:
                connect_wifi()
                pool = socketpool.SocketPool(wifi.radio)
                connected = True
                scan_window(pool)
            except Exception as e:
                status_lbl.text = "wifi failed: %s" % str(e)[:16]
                status_lbl.color = 0xFF4040
                display.refresh()
        time.sleep(0.1)
        continue

    if p2:
        scan_window(pool)
        time.sleep(0.2)
    elif p3:
        # next window of hosts (.13.. .24, etc.), wrap within valid range
        _window = (_window + HOST_COUNT) % (MAX_WINDOW + 1)
        scan_window(pool)
        time.sleep(0.2)
    elif p1:
        _window = (_window - HOST_COUNT) % (MAX_WINDOW + 1)
        scan_window(pool)
        time.sleep(0.2)

    time.sleep(0.05)
