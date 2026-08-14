"""
code.py -- TOTP Authenticator (2FA token)
====================================================================
Turns the badge into a time-based one-time-password (TOTP) token, the
same algorithm Google Authenticator / Authy use for two-factor login.

It syncs the clock over WiFi using a ~30-line hand-written NTP client
(no extra library), then computes a 6-digit code every 30 seconds with
RFC 6238 / HMAC-SHA1. The code is verifiable: the default secret is
the well-known RFC test vector "JBSWY3DPEHPK3PXP", so you can check
the badge's output against any online TOTP generator.

To use it with your own account: copy your 2FA secret (the base32
string, no spaces) into SECRET_B32 below and set ACCOUNT. Your secret
lives only in this file -- it is NOT uploaded anywhere and is never
written to NVM -- so editing the code is how you "provision" the badge.

Controls
--------
  SW3 (IO43)  -- re-sync the clock over NTP (also retries after error)
"""

import os
import time
import struct
import hashlib
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
#  Configuration -- edit these for your own account
# ==============================================================
WIFI_SSID = os.getenv("WIFI_SSID", "your-wifi-name")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "your-wifi-password")

# Base32 secret (uppercase, no spaces). Default = RFC test vector so
# the displayed code matches any online TOTP generator for verification.
SECRET_B32 = "JBSWY3DPEHPK3PXP"
ACCOUNT = "DEMO"
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


# ------------------------------------------------------------------
# Base32 + HMAC-SHA1 + TOTP
# ------------------------------------------------------------------
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def b32decode(s):
    """RFC 4648 base32 decode (ignores spaces and padding)."""
    s = s.upper().replace(" ", "").replace("=", "")
    bits = 0
    nbits = 0
    out = bytearray()
    for c in s:
        v = _B32.find(c)
        if v < 0:
            continue
        bits = (bits << 5) | v
        nbits += 5
        if nbits >= 8:
            nbits -= 8
            out.append((bits >> nbits) & 0xFF)
    return bytes(out)


def _sha1_pure(data):
    """Pure-Python RFC 3174 SHA-1 (fallback for builds without hashlib.sha1)."""
    h0, h1, h2, h3, h4 = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0

    msg = bytearray(data)
    ml = len(msg) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += struct.pack(">Q", ml)

    for i in range(0, len(msg), 64):
        chunk = msg[i:i + 64]
        w = list(struct.unpack(">16L", bytes(chunk)))
        for t in range(16, 80):
            v = w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16]
            w.append(((v << 1) | (v >> 31)) & 0xFFFFFFFF)

        a, b, c, d, e = h0, h1, h2, h3, h4
        for t in range(80):
            if t < 20:
                f = (b & c) | ((~b) & d)
                k = 0x5A827999
            elif t < 40:
                f = b ^ c ^ d
                k = 0x6ED9EBA1
            elif t < 60:
                f = (b & c) | (b & d) | (c & d)
                k = 0x8F1BBCDC
            else:
                f = b ^ c ^ d
                k = 0xCA62C1D6
            temp = (((a << 5) | (a >> 27)) + f + e + k + w[t]) & 0xFFFFFFFF
            e = d
            d = c
            c = ((b << 30) | (b >> 2)) & 0xFFFFFFFF
            b = a
            a = temp

        h0 = (h0 + a) & 0xFFFFFFFF
        h1 = (h1 + b) & 0xFFFFFFFF
        h2 = (h2 + c) & 0xFFFFFFFF
        h3 = (h3 + d) & 0xFFFFFFFF
        h4 = (h4 + e) & 0xFFFFFFFF

    return struct.pack(">5L", h0, h1, h2, h3, h4)


_HAS_HASHLIB_SHA1 = hasattr(hashlib, "sha1")


def sha1(data):
    if _HAS_HASHLIB_SHA1:
        h = hashlib.sha1()
        h.update(data)
        return h.digest()
    return _sha1_pure(data)


def hmac_sha1(key, msg):
    block = 64
    if len(key) > block:
        key = sha1(key)
    key = key + (b"\x00" * (block - len(key)))
    o_pad = bytes(b ^ 0x5C for b in key)
    i_pad = bytes(b ^ 0x36 for b in key)
    return sha1(o_pad + sha1(i_pad + msg))


def totp(secret_b32, unix_time, step=30, digits=6):
    key = b32decode(secret_b32)
    counter = int(unix_time // step)
    msg = struct.pack(">Q", counter)
    mac = hmac_sha1(key, msg)
    offset = mac[-1] & 0x0F
    binary = (((mac[offset] & 0x7F) << 24)
              | (mac[offset + 1] << 16)
              | (mac[offset + 2] << 8)
              | (mac[offset + 3]))
    code = binary % (10 ** digits)
    s = str(code)
    s = "0" * (digits - len(s)) + s
    return s, counter


# ------------------------------------------------------------------
# Display
# ------------------------------------------------------------------
code_scene = displayio.Group()
bg = displayio.Bitmap(128, 160, 1)
bp = displayio.Palette(1); bp[0] = 0x000A12
code_scene.append(displayio.TileGrid(bg, pixel_shader=bp, x=0, y=0))

title_lbl = label.Label(terminalio.FONT, text="AUTHENTICATOR", color=0x00FFCC, x=14, y=6)
acct_lbl = label.Label(terminalio.FONT, text=ACCOUNT, color=0xFFFF66, scale=2, x=8, y=24)
code_lbl = label.Label(terminalio.FONT, text="------", color=0xFFFFFF, scale=3, x=10, y=52)

# countdown bar
bar_pal = displayio.Palette(3)
bar_pal[0] = 0x101418
bar_pal[1] = 0x00FF66
bar_pal[2] = 0xFF4444
BAR_W = 108
bar_bmp = displayio.Bitmap(BAR_W, 8, 3)
code_scene.append(displayio.TileGrid(bar_bmp, pixel_shader=bar_pal, x=10, y=86))

status_lbl = label.Label(terminalio.FONT, text="", color=0x808080, x=6, y=104)
secret_lbl = label.Label(terminalio.FONT, text="key: " + SECRET_B32[:18], color=0x505050, x=4, y=128)
hint_lbl = label.Label(terminalio.FONT, text="SW3 re-sync", color=0x404040, x=4, y=152)
for l in (title_lbl, acct_lbl, code_lbl, status_lbl, secret_lbl, hint_lbl):
    code_scene.append(l)

err_scene = displayio.Group()
ebg = displayio.Bitmap(128, 160, 1)
ep = displayio.Palette(1); ep[0] = 0x400000
err_scene.append(displayio.TileGrid(ebg, pixel_shader=ep, x=0, y=0))
err_title = label.Label(terminalio.FONT, text="", scale=2, color=0xFFFF00, x=10, y=12)
err_lines = []
for i in range(8):
    lb = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=8, y=42 + i * 12)
    err_lines.append(lb); err_scene.append(lb)
err_foot = label.Label(terminalio.FONT, text="SW3 to retry", color=0xFFC000, x=8, y=150)
err_scene.append(err_title); err_scene.append(err_foot)

display.root_group = code_scene


def show_error(title, lines):
    err_title.text = title
    for i, lb in enumerate(err_lines):
        lb.text = lines[i] if i < len(lines) else ""
    pixels.fill((60, 0, 0)); pixels.show()
    display.root_group = err_scene
    display.refresh()
    print("!", title, lines)


# ------------------------------------------------------------------
# Networking: WiFi + tiny NTP client
# ------------------------------------------------------------------
def connect_wifi():
    status_lbl.text = "wifi: connecting..."
    status_lbl.color = 0xFFFF00
    display.refresh()
    pixels.fill((30, 30, 0)); pixels.show()
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    status_lbl.text = "wifi up %s" % wifi.radio.ipv4_address
    status_lbl.color = 0x00A000
    display.refresh()


def ntp_unix():
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
        return secs - 2208988800
    finally:
        s.close()


unix_at_sync = 0
mono_at_sync = 0.0
synced = False


def now_unix():
    return unix_at_sync + (time.monotonic() - mono_at_sync)


def do_sync():
    global unix_at_sync, mono_at_sync, synced
    if not wifi.radio.connected:
        connect_wifi()
    status_lbl.text = "ntp: syncing..."
    status_lbl.color = 0xFFFF00
    display.refresh()
    u = ntp_unix()
    unix_at_sync = u
    mono_at_sync = time.monotonic()
    synced = True
    pixels.fill((0, 30, 0)); pixels.show()
    print("NTP sync unix =", u, "->", time.localtime(u))


# ------------------------------------------------------------------
# Render
# ------------------------------------------------------------------
def render_code():
    u = now_unix()
    code, counter = totp(SECRET_B32, u)
    secs_in = u % 30
    secs_left = 30 - secs_in
    code_lbl.text = code
    # countdown bar: fills down from full -> empty over the 30s window
    filled = int(BAR_W * secs_left / 30)
    col = 2 if secs_left <= 5 else 1   # red in the last 5s
    bitmaptools.fill_region(bar_bmp, 0, 0, BAR_W, 8, 0)
    if filled:
        bitmaptools.fill_region(bar_bmp, 0, 0, filled, 8, col)
    # LEDs: time-left bar, last LED blinks red in final 5s
    n = (secs_left * 5 + 29) // 30     # 5..0
    blink = (secs_left <= 5) and (int(time.monotonic() * 4) % 2 == 0)
    for i in range(5):
        if i < n:
            pixels[i] = (0, 200, 80)
        elif i == n and blink:
            pixels[i] = (255, 40, 40)
        else:
            pixels[i] = (0, 0, 0)
    pixels.show()
    status_lbl.text = "synced via NTP  %2ds" % secs_left
    display.refresh()


# ------------------------------------------------------------------
# Boot
# ------------------------------------------------------------------
acct_lbl.text = ACCOUNT
title_lbl.text = "AUTHENTICATOR"
display.refresh()
bl.value = True

if not _HAS_HASHLIB_SHA1:
    print("hashlib.sha1 not available on this build; using pure-Python SHA1 fallback")

try:
    do_sync()
except Exception as e:
    print("sync failed:", e)
    msg = str(e).lower()
    if "auth" in msg or "password" in msg or "ssid" in msg or "not found" in msg:
        show_error("WIFI ERROR", ["", '"%s"' % WIFI_SSID, "", "Check WIFI_SSID /",
                                  "WIFI_PASSWORD in", "settings.toml"])
    else:
        show_error("NTP ERROR", ["", "Reached WiFi but", "NTP sync failed:", "",
                                 str(e)[:20], "", "Check DNS / UDP 123"])

last_sync = time.monotonic()
last_render = 0.0
s3p = True

while True:
    now = time.monotonic()
    p3 = (not sw3.value) and s3p
    s3p = sw3.value

    if not synced:
        if p3:
            try:
                do_sync()
                display.root_group = code_scene
            except Exception as e:
                show_error("NTP ERROR", ["", "retry failed:", "", str(e)[:20]])
            time.sleep(0.3)
        time.sleep(0.05)
        continue

    if p3:
        try:
            do_sync()
        except Exception as e:
            status_lbl.text = "resync failed"
            status_lbl.color = 0xFF4040
            display.refresh()
        time.sleep(0.3)

    # resync hourly
    if now - last_sync > 3600:
        try:
            do_sync()
        except Exception:
            pass
        last_sync = now

    if now - last_render > 0.5:
        render_code()
        last_render = now
    time.sleep(0.05)
