# BadgeHub

Connects to the badge-hub server over WiFi and turns the badge into a
live conference companion: broadcasts, LED light commands, a room mood
board, and live polls, plus a clock view.

## Setup

Put your WiFi credentials in `settings.toml`:

```
WIFI_SSID = "your-wifi"
WIFI_PASSWORD = "your-password"
```

Set the server URL in `code.py` (`SERVER_URL`) if you're not using the
default. See `server/` in this repo for the badge-hub server itself.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1)  | Cycle mood (happy / excited / tired / hungry / cool) |
| SW2 (IO2)  | Vote in the active poll (cycles options, press to vote) |
| SW3 (IO43) | Toggle between hub view and clock view |

## OTA updates

BadgeHub doubles as the OTA client for this repo's `samples/`, `lib/`,
and `mods/` directories. Every 60 seconds (and once right after boot) it
asks the server for `/api/ota/manifest` -- a hash of every top-level
entry in each of those three directories, as bundled into the server's
image -- and compares it against `/samples/.ota_state.json` on the
badge. Anything whose hash changed gets downloaded straight onto the
CIRCUITPY drive via `/api/ota/file`, then BadgeHub reboots
(`supervisor.reload()`) to pick it up.

- `samples/<Name>/...` -- every sample folder.
- `lib/<package>/...` or `lib/<file>.mpy` -- library packages and
  standalone files.
- `mods/<file>` -- the badge-mod runtime's modules (see `mods/README.md`).

Shipping an update is just redeploying the server with new code
committed to this repo -- there's no separate publish step.

This needs write access to the badge's own filesystem, the same
constraint GifPlayer's GIPHY mode runs into: CircuitPython grants write
access to exactly one of the badge and a host computer at a time. If a
computer has CIRCUITPY mounted, OTA checks quietly no-op (a message
goes to the serial console, nothing changes on screen) and retry on the
next check. Updates apply normally when the badge is running untethered
on battery.
