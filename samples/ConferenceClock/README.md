# Conference Clock

A live NTP-synced clock with a configurable timezone and a countdown
to the next session on the conference schedule. It syncs against
`pool.ntp.org` using a ~30-line hand-written NTP client over UDP — no
extra library needed — and re-syncs hourly. The 5 NeoPixels form a
seconds progress bar.

## What you should see

- A big `HH:MM:SS` clock and a date line (`Wed  Sep 10 2025`).
- A **NEXT** block showing the upcoming session title and a countdown
  (`in 2h 14m`), or **NOW** with the minutes left if a session is in
  progress.
- The seconds filling/draining a 5-LED cyan bar.
- A small status footer with the badge's IP and sync state.

## Configuration

- **WiFi** — copy `settings.toml.example` to `settings.toml` and set
  `WIFI_SSID` / `WIFI_PASSWORD`.
- **Time zone** — edit `TZ_OFFSET_HOURS` at the top of `code.py`
  (negative west of Greenwich). Default is `-5` (US Eastern Standard);
  use `-4` for Eastern Daylight Time.
- **Schedule** — edit the `SCHEDULE` list at the top: each entry is a
  `{"start": "HH:MM", "title": "...", "dur": minutes}` in **local**
  time. Add/remove freely; the next-session logic handles wrapping
  to the first session tomorrow.

## Controls

| Switch | Action |
|--------|--------|
| SW3 (IO43) | Manual re-sync over NTP (also retries after an error) |

## Code design

- **Hand-rolled NTP client** — `ntp_unix()` opens a UDP socket to
  `pool.ntp.org:123`, sends the 48-byte client packet (`byte[0] = 0x1B`),
  and reads the 32-bit transmit timestamp from bytes 40–43, subtracting
  the 1900→1970 epoch offset (2208988800). No `adafruit_ntp` dependency.
- **Monotonic ↔ unix offset** — at sync time we store
  `unix_at_sync` and `mono_at_sync`; `now_unix()` returns
  `unix_at_sync + (monotonic - mono_at_sync)`. This avoids relying on a
  settable RTC and stays accurate between hourly re-syncs.
- **Local time via `time.localtime`** — `time.localtime(unix + tz*3600)`
  does all the date/leap-year/weekday math for us, so there's no
  hand-rolled calendar code.
- **Next-session logic** — sessions are sorted by seconds-of-day; we
  find the one in progress, else the next today, else the first tomorrow
  (computed as `start + 86400`), and format the countdown as `Xh Ym`.
- **Two scenes** — a clock scene and a red error scene (WiFi/NTP
  failure) with a `SW3 to retry` footer, mirroring the Weather sample's
  error pattern so attendees know what to check.

## Notes

- NTP uses outbound UDP 123, which is allowed on most networks but
  occasionally blocked by captive portals — if sync fails on
  conference Wi-Fi, the error screen says exactly that.
