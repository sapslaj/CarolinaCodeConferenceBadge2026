# WiFi Scanner

Live WiFi scanner and signal-strength meter for the conference badge. Passively lists nearby networks and lets you monitor any one of them in real time as you walk around.

## Modes

**LIST mode** — All visible networks sorted by strongest RSSI. Auto-rescans every 30 seconds. The 5 NeoPixels mirror the highlighted network's signal strength as a bar graph.

**MONITOR mode** — Full-screen live view of a single network. A fast single-channel rescan runs continuously so the on-screen bar and LEDs update in near real time. Ideal for signal tracing.

## Controls

|   Switch   |                  Action                    |
|------------|--------------------------------------------|
| SW1 (IO1)  | Navigate up                                |
| SW2 (IO2)  | Select / back (enter or exit monitor mode) |
| SW3 (IO43) | Navigate down                              |

## Signal quality visualization

|   RSSI    |        LEDs         |
|-----------|---------------------|
| ≥ −50 dBm | 5 green (excellent) |
| ≥ −60 dBm | 4 green (strong)    |
| ≥ −70 dBm | 3 yellow (fair)     |
| ≥ −80 dBm | 2 orange (weak)     |
| < −80 dBm | 1 red (very weak)   |

## Code design

- **Two `displayio.Group` scenes** (`list_scene`, `monitor_scene`) are built once at startup. Switching modes only reassigns `display.root_group`. No widgets are re-created at runtime.
- **Shared bar palette** (`bar_pal`) is reused for both the small per-row bars and the big monitor-mode bar, keeping memory usage low.
- **Two scan primitives**:
  - `full_scan_with_chase()` — full-spectrum scan with an LED chase animation while it runs, executed every 30 s in list mode.
  - `single_channel_scan(channel, ssid)` — restricted to the selected network's channel for fast, near-real-time updates in monitor mode.
- **Edge-triggered button handling** (`sw_edge`) — switch state is compared to the previous sample so each press registers exactly once.
- **RSSI → visual mappings** are pure helper functions (`rssi_to_quality`, `rssi_to_bars`, `rssi_led_color`, etc.) so both the on-screen bar and the LED strip stay consistent.
- **No credentials required** — this is purely passive scanning, so it works with no `settings.toml` changes.
