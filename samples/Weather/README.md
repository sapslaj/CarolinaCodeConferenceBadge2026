# Weather

Full weather app on the badge. Connects to WiFi, converts a US ZIP code to lat/lon, fetches current conditions plus a 3-day forecast, and shows it on the display. The 5 NeoPixels double as a color-coded temperature dashboard.

No API keys required — both web services (zippopotam.us and open-meteo.com) are free and open.

## Configuration

1. Set your WiFi credentials once, at the top level of the drive, in `settings.toml`. On first setup, copy `settings.toml.example` to `settings.toml` and edit these two lines:

   ```toml
   WIFI_SSID     = "your-network"
   WIFI_PASSWORD = "your-password"
   ```

   These are shared by every sample that connects to the internet. (Note: the keys deliberately don't use the `CIRCUITPY_WIFI_*` magic names — see the comment at the top of `settings.toml.example` for why.)

2. Edit the ZIP code near the top of `code.py`:

   ```python
   ZIP_CODE = "29605"
   ```

## Controls

- **BOOT button (IO0)** — manual refresh / retry.
- Auto-refreshes every 15 minutes.

## What you should see

- Header: ZIP code + resolved city/state.
- Big current temperature (color-coded by heat).
- Current conditions label (Clear, Rain, Snow, T-Storm, etc.) + humidity + wind.
- Three-day forecast rows: today / tomorrow / +2 days.
- NeoPixel dashboard:
  - Pixel 0 — current temperature color.
  - Pixels 1–3 — the three daily highs.
  - Pixel 4 — condition color (e.g. yellow = clear, blue = rain, purple = t-storm).
- On any failure: a full-screen red error screen naming exactly which config variable to check.

## Code design

- **Two `displayio.Group` scenes** — `normal_scene` and `error_scene`. Switching between them is a single assignment to `display.root_group`, no re-rendering needed.
- **Single-entry retry** — `try_refresh()` runs the three-step pipeline (WiFi → ZIP → weather) and catches exceptions at each stage. Each failure classifies itself into a workshop-friendly error screen that names the offending config variable (`WIFI_SSID`, `WIFI_PASSWORD`, `ZIP_CODE`).
- **WiFi error triage** — `wifi_error_screen()` inspects the exception text for `"auth"`, `"ssid"`, `"timeout"` keywords and shows a targeted "check WIFI_PASSWORD" / "SSID missing" / "signal too weak" screen instead of a raw traceback.
- **Lazy HTTPS session** — a single `adafruit_requests.Session` (backed by `socketpool` + `ssl`) is created on first use and reused for both API calls. Saves TLS handshake cost on the ~15-minute refresh cycle.
- **WMO code → (label, color) table** — the open-meteo API returns numeric weather codes; `WMO` maps each one to both a short display label and a NeoPixel color, so pixel 4 becomes an at-a-glance weather icon.
- **Temperature-to-color ramp** — `temp_rgb(f)` uses discrete thresholds (32 / 50 / 70 / 85 °F) to produce ice-blue → cool-blue → green → orange → red. Applied to both the display text and NeoPixels 0–3 so they stay in sync.
- **Serial mirror** — every render also prints a boxed summary to the USB serial console, useful when the display is off or you're debugging headless.
- **`settings.toml`** — WiFi credentials come from `os.getenv()`, so this sample works on any drive that has valid credentials without editing `code.py`.
