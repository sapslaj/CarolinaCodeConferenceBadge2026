"""
code_WiFi_Scanner.py -- Carolina Code Conference sample
========================================================
Live WiFi scanner + signal-strength meter for the ESP32-S3-DevKitC
conference kit (128x160 ST7735R TFT + 5-pixel NeoPixel strip).

Two modes
---------
  LIST MODE      -- shows nearby networks sorted by strongest RSSI.
                    Rescans every 30 seconds.
                    The 5 NeoPixels display the highlighted
                    network's last-known signal.

  MONITOR MODE   -- full-screen live view of ONE network.
                    Single-channel rescan runs continuously so the
                    LEDs + on-screen bar update in near-real-time.
                    Perfect for walking around to trace signal.

Controls (Switch numbers from the conference kit)
-------------------------------------------------
  SW1 (IO1)      -- navigate UP     (both modes)
  SW2 (IO2)      -- SELECT / back   (enter or exit monitor mode)
  SW3 (IO43)     -- navigate DOWN   (both modes)

Signal quality visualization
----------------------------
  RSSI >= -50 dBm  -- 5 LEDs green   (excellent)
  RSSI >= -60 dBm  -- 4 LEDs green   (strong)
  RSSI >= -70 dBm  -- 3 LEDs yellow  (fair)
  RSSI >= -80 dBm  -- 2 LEDs orange  (weak)
  RSSI <  -80 dBm  -- 1 LED  red     (very weak)

No credentials required -- pure passive scanning.
"""

import time
import board
import busio
import digitalio
import displayio
import fourwire
import neopixel
import terminalio
import wifi
import bitmaptools
import adafruit_st7735r
from adafruit_display_text import label


# ------------------------------------------------------------------
# Hardware setup
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

# Three tactile switches -- pull-down wired, use internal pullup
sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

# Font-ROM chip must stay deselected so the display owns the SPI bus
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

# Display backlight -- keep off until the first frame is drawn
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False

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
    display_bus, width=128, height=160, rotation=0, bgr=True, auto_refresh=False,
)


# ------------------------------------------------------------------
# Signal-strength helpers
# ------------------------------------------------------------------
def rssi_to_quality(rssi):
    """Map RSSI (dBm) to a 0.0-1.0 quality value for the bar length."""
    if rssi is None:  return 0.0
    if rssi >= -30:   return 1.0
    if rssi <= -90:   return 0.0
    return (rssi + 90) / 60.0


def rssi_to_bars(rssi):
    """0..5 signal-bar count (like a phone icon)."""
    if rssi is None:  return 0
    if rssi >= -50:   return 5
    if rssi >= -60:   return 4
    if rssi >= -70:   return 3
    if rssi >= -80:   return 2
    if rssi >= -90:   return 1
    return 0


def rssi_quality_label(rssi):
    n = rssi_to_bars(rssi)
    return ("NO SIGNAL", "VERY WEAK", "WEAK", "FAIR", "STRONG", "EXCELLENT")[n]


def rssi_led_color(rssi):
    n = rssi_to_bars(rssi)
    if n >= 4: return (  0, 255,   0)   # green
    if n == 3: return (255, 200,   0)   # yellow
    if n == 2: return (255, 100,   0)   # orange
    if n == 1: return (255,   0,   0)   # red
    return             (  0,   0,   0)  # off (no signal)


def rssi_bar_palette_idx(rssi):
    n = rssi_to_bars(rssi)
    if n >= 4: return 1   # green
    if n == 3: return 2   # yellow
    if n == 2: return 3   # orange
    if n == 1: return 4   # red
    return 0               # unfilled


def auth_short(modes):
    if not modes:                          return "?   "
    if wifi.AuthMode.ENTERPRISE in modes:  return "ENT "
    if wifi.AuthMode.OPEN       in modes:  return "OPEN"
    if wifi.AuthMode.WPA3       in modes:  return "WPA3"
    if wifi.AuthMode.WPA2       in modes:  return "WPA2"
    if wifi.AuthMode.WPA        in modes:  return "WPA "
    if wifi.AuthMode.WEP        in modes:  return "WEP "
    return "?   "


def auth_color(modes):
    if not modes:                          return 0x606060
    if wifi.AuthMode.OPEN in modes:        return 0xFF4040   # red -- insecure
    if wifi.AuthMode.WEP  in modes:        return 0xFF8800   # orange -- weak
    if wifi.AuthMode.WPA3 in modes:        return 0x40FFA0   # mint  -- strong
    return 0x40FF40                                           # green -- WPA/WPA2


def update_led_meter(rssi):
    """Light the strip as a bar-graph of the current signal (0..5 LEDs)."""
    if rssi is None:
        pixels.fill((0, 0, 0))
        pixels[0] = (30, 0, 0)          # single dim-red = "no signal"
        pixels.show()
        return
    n = rssi_to_bars(rssi)
    color = rssi_led_color(rssi)
    for i in range(5):
        pixels[i] = color if i < n else (8, 8, 8)   # dim off-white for unlit
    pixels.show()


# ==================================================================
# Scene 1 -- list mode
# ==================================================================
MAX_ROWS = 5
ROW_Y0   = 32
ROW_H    = 22
BAR_W    = 78
BAR_H    = 6
BAR_X    = 14

list_scene = displayio.Group()

bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1); bg_pal[0] = 0x000010
list_scene.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

title_lbl = label.Label(terminalio.FONT, text="WIFI SCANNER",
                        color=0xFFFF00, x=22, y=8)
count_lbl = label.Label(terminalio.FONT, text="scanning...",
                        color=0x808080, x=6, y=22)
list_scene.append(title_lbl); list_scene.append(count_lbl)

# Shared palette for on-screen bar graphs
bar_pal = displayio.Palette(5)
bar_pal[0] = 0x202020
bar_pal[1] = 0x00FF00
bar_pal[2] = 0xFFFF00
bar_pal[3] = 0xFF8800
bar_pal[4] = 0xFF0000

row_ssid = []; row_bar = []; row_rssi = []; row_auth = []

for i in range(MAX_ROWS):
    top     = ROW_Y0 + i * ROW_H
    y_label = top + 6
    y_bar   = top + 15

    ssid_lbl = label.Label(terminalio.FONT, text="", color=0xA0A0A0, x=6, y=y_label)
    list_scene.append(ssid_lbl); row_ssid.append(ssid_lbl)

    auth_lbl = label.Label(terminalio.FONT, text="", color=0x40FF40, x=98, y=y_label)
    list_scene.append(auth_lbl); row_auth.append(auth_lbl)

    bmp = displayio.Bitmap(BAR_W, BAR_H, 5)
    tg  = displayio.TileGrid(bmp, pixel_shader=bar_pal,
                             x=BAR_X, y=y_bar - BAR_H // 2)
    list_scene.append(tg); row_bar.append(bmp)

    rssi_lbl = label.Label(terminalio.FONT, text="", color=0x808080,
                           x=BAR_X + BAR_W + 4, y=y_bar)
    list_scene.append(rssi_lbl); row_rssi.append(rssi_lbl)

list_footer = label.Label(terminalio.FONT, text="SW1/3 nav  SW2 select",
                          color=0x606060, x=6, y=154)
list_scene.append(list_footer)


# ==================================================================
# Scene 2 -- monitor mode (single network, full-screen live view)
# ==================================================================
monitor_scene = displayio.Group()

mbg = displayio.Bitmap(128, 160, 1)
mbg_pal = displayio.Palette(1); mbg_pal[0] = 0x000018
monitor_scene.append(displayio.TileGrid(mbg, pixel_shader=mbg_pal))

mon_title = label.Label(terminalio.FONT, text="MONITORING",
                        color=0x00FFFF, x=32, y=8)
monitor_scene.append(mon_title)

mon_ssid = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=6, y=24)
monitor_scene.append(mon_ssid)

mon_meta = label.Label(terminalio.FONT, text="", color=0x808080, x=6, y=38)
monitor_scene.append(mon_meta)

# HUGE RSSI number, scale=3, auto-centered via anchor_point
mon_rssi = label.Label(terminalio.FONT, text="---", scale=3, color=0xFFFFFF)
mon_rssi.anchor_point = (0.5, 0.5)
mon_rssi.anchored_position = (64, 72)
monitor_scene.append(mon_rssi)

mon_unit = label.Label(terminalio.FONT, text="dBm", color=0x808080)
mon_unit.anchor_point = (0.5, 0.5)
mon_unit.anchored_position = (64, 100)
monitor_scene.append(mon_unit)

# Big horizontal bar
BIG_BAR_W = 116
BIG_BAR_H = 10
big_bar_bmp = displayio.Bitmap(BIG_BAR_W, BIG_BAR_H, 5)
big_bar_tg  = displayio.TileGrid(big_bar_bmp, pixel_shader=bar_pal, x=6, y=114)
monitor_scene.append(big_bar_tg)

mon_quality = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
mon_quality.anchor_point = (0.5, 0.5)
mon_quality.anchored_position = (64, 138)
monitor_scene.append(mon_quality)

mon_footer = label.Label(terminalio.FONT, text="SW2 back  SW1/3 prev/next",
                         color=0x606060, x=4, y=154)
monitor_scene.append(mon_footer)


# ------------------------------------------------------------------
# Render helpers
# ------------------------------------------------------------------
def clear_row(i):
    row_ssid[i].text = ""
    row_rssi[i].text = ""
    row_auth[i].text = ""
    bitmaptools.fill_region(row_bar[i], 0, 0, BAR_W, BAR_H, 0)


def draw_row_bar(i, rssi):
    q = rssi_to_quality(rssi)
    filled = int(BAR_W * q)
    color_idx = rssi_bar_palette_idx(rssi)
    bitmaptools.fill_region(row_bar[i], 0, 0, BAR_W, BAR_H, 0)
    if filled > 0:
        bitmaptools.fill_region(row_bar[i], 0, 0, filled, BAR_H, color_idx)


def draw_big_bar(rssi):
    q = rssi_to_quality(rssi)
    filled = int(BIG_BAR_W * q)
    color_idx = rssi_bar_palette_idx(rssi)
    bitmaptools.fill_region(big_bar_bmp, 0, 0, BIG_BAR_W, BIG_BAR_H, 0)
    if filled > 0:
        bitmaptools.fill_region(big_bar_bmp, 0, 0, filled, BIG_BAR_H, color_idx)


def render_list(networks, selected_idx, visible_start):
    for i in range(MAX_ROWS):
        net_i = visible_start + i
        if net_i < len(networks):
            n = networks[net_i]
            selected = (net_i == selected_idx)
            ssid = n["ssid"][:13]
            marker = ">" if selected else " "
            row_ssid[i].text  = "%s %s" % (marker, ssid)
            row_ssid[i].color = 0xFFFFFF if selected else 0xA0A0A0
            row_auth[i].text  = auth_short(n["auth"]).strip()
            row_auth[i].color = auth_color(n["auth"])
            draw_row_bar(i, n["rssi"])
            row_rssi[i].text  = "%d" % n["rssi"]
            row_rssi[i].color = 0xFFFFFF if selected else 0x606060
        else:
            clear_row(i)
    if networks:
        count_lbl.text  = "%d networks  [%d/%d]" % (
            len(networks), selected_idx + 1, len(networks))
    else:
        count_lbl.text  = "no networks found"
    count_lbl.color = 0x808080
    display.refresh()


def render_monitor(network, rssi, seconds_since_seen):
    """Update the monitor scene with a new RSSI sample."""
    mon_ssid.text = network["ssid"][:20]

    ch = network.get("ch", "?")
    auth = auth_short(network["auth"]).strip()
    mon_meta.text  = "channel %s   %s" % (ch, auth)
    mon_meta.color = auth_color(network["auth"])

    if rssi is None:
        mon_rssi.text     = "---"
        mon_rssi.color    = 0xFF4040
        mon_quality.text  = "SIGNAL LOST"
        mon_quality.color = 0xFF4040
        bitmaptools.fill_region(big_bar_bmp, 0, 0, BIG_BAR_W, BIG_BAR_H, 0)
    else:
        mon_rssi.text     = "%d" % rssi
        mon_rssi.color    = 0xFFFFFF
        mon_quality.text  = "%s (%.1fs)" % (rssi_quality_label(rssi), seconds_since_seen)
        mon_quality.color = auth_color(network["auth"]) if seconds_since_seen < 1.5 else 0x808080
        draw_big_bar(rssi)

    display.refresh()


# ------------------------------------------------------------------
# Scans
# ------------------------------------------------------------------
def full_scan_with_chase():
    """Full scan across all channels. Animates the LED chase while it runs."""
    count_lbl.text  = "scanning..."
    count_lbl.color = 0xFFFF00
    display.refresh()

    networks = []
    chase_pos  = 0
    chase_last = time.monotonic()

    try:
        for n in wifi.radio.start_scanning_networks():
            networks.append({
                "ssid": n.ssid,
                "rssi": n.rssi,
                "ch":   n.channel,
                "auth": list(n.authmode),
            })
            now = time.monotonic()
            if now - chase_last > 0.08:
                for i in range(5):
                    pixels[i] = (0, 60, 120) if i == chase_pos else (0, 0, 0)
                pixels.show()
                chase_pos  = (chase_pos + 1) % 5
                chase_last = now
    finally:
        wifi.radio.stop_scanning_networks()

    networks.sort(key=lambda x: -x["rssi"])
    print("scan complete:", len(networks), "networks")
    for n in networks:
        print("  %-24r rssi=%4d ch=%2d auth=%s"
              % (n["ssid"], n["rssi"], n["ch"], auth_short(n["auth"]).strip()))
    return networks


def single_channel_scan(channel, target_ssid):
    """Fast rescan restricted to a single channel. Returns RSSI or None."""
    latest = None
    try:
        for n in wifi.radio.start_scanning_networks(
                start_channel=channel, stop_channel=channel):
            if n.ssid == target_ssid:
                latest = n.rssi
    finally:
        wifi.radio.stop_scanning_networks()
    return latest


# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------
MODE_LIST    = 0
MODE_MONITOR = 1

mode           = MODE_LIST
networks       = []
selected_idx   = 0
selected_ssid  = None
visible_start  = 0

# For monitor mode
monitor_last_seen_time = 0.0
monitor_last_rssi      = None


def clamp_visible():
    """Keep the visible window covering selected_idx."""
    global visible_start
    if selected_idx < visible_start:
        visible_start = selected_idx
    elif selected_idx >= visible_start + MAX_ROWS:
        visible_start = selected_idx - MAX_ROWS + 1
    if visible_start < 0:
        visible_start = 0


def move_selection(delta):
    """Adjust selection wrapped; update LEDs; scroll if needed."""
    global selected_idx, selected_ssid
    if not networks:
        return
    selected_idx = (selected_idx + delta) % len(networks)
    selected_ssid = networks[selected_idx]["ssid"]
    clamp_visible()


def enter_monitor():
    global mode, monitor_last_seen_time, monitor_last_rssi
    if not networks:
        return
    print("-> MONITOR:", networks[selected_idx]["ssid"])
    mode = MODE_MONITOR
    monitor_last_seen_time = time.monotonic()
    monitor_last_rssi = networks[selected_idx]["rssi"]
    display.root_group = monitor_scene
    render_monitor(networks[selected_idx], monitor_last_rssi, 0.0)
    update_led_meter(monitor_last_rssi)


def exit_monitor():
    global mode
    print("-> LIST")
    mode = MODE_LIST
    display.root_group = list_scene
    render_list(networks, selected_idx, visible_start)
    if networks:
        update_led_meter(networks[selected_idx]["rssi"])


# ------------------------------------------------------------------
# Boot
# ------------------------------------------------------------------
count_lbl.text = "starting..."
display.root_group = list_scene
display.refresh()
bl.value = True

networks = full_scan_with_chase()
if networks:
    selected_idx  = 0
    selected_ssid = networks[0]["ssid"]
    update_led_meter(networks[0]["rssi"])
else:
    pixels.fill((30, 0, 0)); pixels.show()

clamp_visible()
render_list(networks, selected_idx, visible_start)


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
SCAN_INTERVAL_LIST = 30.0    # seconds between full scans in LIST mode
last_full_scan     = time.monotonic()

sw1_prev = True
sw2_prev = True
sw3_prev = True

def sw_edge(prev, curr):
    """Return True on a falling edge (button just pressed)."""
    return (not curr) and prev

while True:
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    pressed_sw1 = sw_edge(sw1_prev, v1)
    pressed_sw2 = sw_edge(sw2_prev, v2)
    pressed_sw3 = sw_edge(sw3_prev, v3)
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    # =========================
    # LIST MODE
    # =========================
    if mode == MODE_LIST:
        if pressed_sw1 and networks:
            move_selection(-1)
            render_list(networks, selected_idx, visible_start)
            update_led_meter(networks[selected_idx]["rssi"])
            time.sleep(0.12)

        elif pressed_sw3 and networks:
            move_selection(+1)
            render_list(networks, selected_idx, visible_start)
            update_led_meter(networks[selected_idx]["rssi"])
            time.sleep(0.12)

        elif pressed_sw2 and networks:
            enter_monitor()
            time.sleep(0.15)

        # 30-second auto-rescan
        now = time.monotonic()
        if now - last_full_scan > SCAN_INTERVAL_LIST:
            networks = full_scan_with_chase()
            if networks:
                # Reacquire selection by SSID
                new_idx = 0
                if selected_ssid:
                    for i, n in enumerate(networks):
                        if n["ssid"] == selected_ssid:
                            new_idx = i
                            break
                selected_idx  = new_idx
                selected_ssid = networks[selected_idx]["ssid"]
                clamp_visible()
                update_led_meter(networks[selected_idx]["rssi"])
            else:
                pixels.fill((30, 0, 0)); pixels.show()
            render_list(networks, selected_idx, visible_start)
            last_full_scan = time.monotonic()

    # =========================
    # MONITOR MODE
    # =========================
    else:
        if pressed_sw2:
            exit_monitor()
            last_full_scan = time.monotonic()   # reset 30s timer on return
            time.sleep(0.15)
            continue

        if pressed_sw1 and networks:
            move_selection(-1)
            monitor_last_rssi = networks[selected_idx]["rssi"]
            monitor_last_seen_time = time.monotonic()
            render_monitor(networks[selected_idx], monitor_last_rssi, 0.0)
            update_led_meter(monitor_last_rssi)
            time.sleep(0.12)
            continue

        if pressed_sw3 and networks:
            move_selection(+1)
            monitor_last_rssi = networks[selected_idx]["rssi"]
            monitor_last_seen_time = time.monotonic()
            render_monitor(networks[selected_idx], monitor_last_rssi, 0.0)
            update_led_meter(monitor_last_rssi)
            time.sleep(0.12)
            continue

        # Fast single-channel rescan for the selected network
        target = networks[selected_idx]
        rssi = single_channel_scan(target["ch"], target["ssid"])
        now = time.monotonic()
        if rssi is not None:
            monitor_last_rssi = rssi
            monitor_last_seen_time = now
            # keep cached copy fresh for the list view
            target["rssi"] = rssi
            update_led_meter(rssi)
        else:
            # signal lost -- fade LEDs and mark stale
            if now - monitor_last_seen_time > 5.0:
                update_led_meter(None)
                monitor_last_rssi = None

        render_monitor(target, monitor_last_rssi, now - monitor_last_seen_time)

    time.sleep(0.02)
