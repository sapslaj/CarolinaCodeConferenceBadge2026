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
badge. That manifest carries hashes only, no file lists, on purpose: an
earlier version returned the full file listing for everything in one
response (~17 KB of JSON) and reliably crashed the badge parsing it. For
whatever changed, BadgeHub fetches that one unit's file list from
`/api/ota/unit`, then the files themselves from `/api/ota/file`, and
reboots (`supervisor.reload()`) to pick them up.

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

Batching, pacing, and telemetry. A badge's very first sync can have
dozens of units pending at once (every sample, lib package, mod, tool).
`OTA_BATCH_LIMIT` (5) caps how many units one check applies -- the rest
wait for the next 60s cycle -- so one check can't block the main loop
(no button/LED service happens during it) for minutes at a stretch.
`OTA_REQUEST_PACE` (0.25s) sits before every OTA-related network call,
including telemetry sends: applying a full batch unpaced was measured
timing out partway through (`ETIMEDOUT` and assorted negative
mbedtls/lwIP error codes) -- this hardware's TLS/socket layer needs a
gap between back-to-back requests, the same lesson `badgexfer.py`
documents for ESP-NOW ("unpaced sends saturate the TX queue"). State
saves after every successfully-applied unit, not just at the end of a
batch, so an interrupted batch keeps its progress instead of retrying
from scratch.

`reload_badge()` sets `wifi.radio.enabled = False` before calling
`supervisor.reload()`. That reload is a soft VM restart, not a hardware
reset -- it doesn't clear ESP-IDF's WiFi state, and reloading right
after a batch of HTTPS OTA fetches (radio associated, TLS session open)
was leaving the *next* boot's `wifi.radio.connect()` failing with
"Authentication failure", credentials unchanged. Same class of gotcha
`badgenet.py` already documents for ESP-NOW needing an explicit
`deinit()` before anything reuses the radio.

A close relative of that bug, worth knowing about: this whole file is
`exec()`'d as one script by the Launcher, top to bottom, and every
docstring becomes a real string object the moment its `def` runs --
*before* `connect_wifi()` is ever reached, since that call sits near
the bottom of the file. A commit that added ~2 KB of prose-heavy
docstrings (bisected to confirm) pushed the module's memory footprint
far enough to start failing that same WPA handshake with the identical
"Authentication failure" message, no code-path connection between the
two at all -- just competing for the same heap at the same moment.
Keep `code.py`'s docstrings and comments terse; put rationale here
instead, in a file that's never executed on the badge and so costs it
nothing. `mods/README.md` documents the identical tradeoff for a
different resource (network airtime instead of RAM), for modules that
travel over ESP-NOW -- same principle, different budget.
