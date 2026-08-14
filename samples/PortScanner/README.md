# Port Scanner (pocket tricorder)

A live TCP port scanner for the conference badge. It joins your WiFi,
works out the local `/24` subnet from the badge's own IP, and probes a
handful of common ports on the first `HOST_COUNT` hosts — drawing each
result into a live grid as it goes. Open ports light up green, closed
hosts show dim, and the cell being probed flashes yellow.

This is the ethical-hacking demo: it only touches the local subnet
you're already on (your own network), and uses short non-aggressive
timeouts. Great for "what's actually listening on my home network?"
walks at a conference.

## What you should see

- A matrix with one row per probed port (22, 23, 80, 443, 445, 3389,
  8080) and one column per host (`.1` … `.12` by default). Each cell
  turns green (open) or dim (closed) as it's scanned, with the active
  cell flashing yellow.
- The status line shows the current `IP:port` being probed, then
  `done. SW2 rescan` when finished.
- The LEDs light up green for each open port found so far (up to 5).
- A legend at the bottom matches the cell colours.

## Configuration

- **WiFi** — copy `settings.toml.example` to `settings.toml` and set
  `WIFI_SSID` / `WIFI_PASSWORD`.
- **`HOST_COUNT`** (default 12) — how many hosts to probe per window.
- **`PROBE_TIMEOUT`** (default 0.12 s) — per-TCP-connect timeout.
- **`PORTS`** — the list of ports to probe on each host.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1) | Scan the **previous** host window (`.1`–`.12` → `.241`–`.252` → …) |
| SW2 (IO2) | **Re-scan** the current window |
| SW3 (IO43) | Scan the **next** host window |

## Code design

- **Subnet inferred from own IP** — `wifi.radio.ipv4_address` is split
  and the first three octets become the `/24` base, so it works on any
  network without configuration.
- **One socket per probe** — `socketpool` TCP socket with
  `settimeout(PROBE_TIMEOUT)`; a successful `connect()` means the port
  is open, any `OSError` (refused, filtered, timeout) means closed.
  Sockets are closed in a `finally` so none leak across the ~84 probes.
- **Live matrix redraw** — each probe updates its cell and refreshes
  immediately, so you watch the scan sweep across the grid. This is
  intentionally sequential (not concurrent) so the visual is legible
  and so the badge stays responsive between probes.
- **Hex host labels** — host octets are shown as single hex digits
  (`1`–`9`, `A`–`F`) to fit the 8 px columns; octets ≥ 16 show `?`.
- **Windowing** — `_window` tracks the first octet of the current
  12-host window and wraps modulo 254, so SW1/SW3 page through the
  whole subnet.

## Notes

- A "closed" result can mean either "actively refused" (host is up,
  no service) or "timed out / filtered" (host down or firewall silent).
  This sample doesn't distinguish — that's the honest trade-off for a
  one-shot 0.12 s probe.
- Scanning networks you don't own may be against their acceptable-use
  policy; keep this to your own home/lab subnet.
