# TOTP Authenticator (2FA token)

Turns the badge into a time-based one-time-password (TOTP) token — the
same RFC 6238 / HMAC-SHA1 algorithm Google Authenticator and Authy use
for two-factor login. It syncs the clock over WiFi with a hand-written
NTP client, then computes a 6-digit code every 30 seconds. The default
secret is the well-known RFC test vector, so the badge's output matches
any online TOTP generator for verification.

## What you should see

- Your account name in yellow and the 6-digit code in big white digits.
- A green countdown bar that empties over the 30-second window and
  turns red in the final 5 seconds.
- The LEDs mirror the countdown as a time-left bar, blinking red in
  the last 5 seconds.
- A footer showing `synced via NTP  Nds` and your base32 key.

## Configuration

1. **WiFi** — copy `settings.toml.example` to `settings.toml` and set
   `WIFI_SSID` / `WIFI_PASSWORD`.
2. **Secret** — copy your account's base32 2FA secret (the string you'd
   paste into an authenticator app, no spaces) into `SECRET_B32`, and set
   `ACCOUNT`. The default `JBSWY3DPEHPK3PXP` is the RFC test vector.

Your secret lives only in this file — it is never uploaded anywhere
and never written to NVM — so editing the code *is* how you provision
the badge.

## Controls

| Switch | Action |
|--------|--------|
| SW3 (IO43) | Re-sync the clock over NTP (also retries after an error) |

## Code design

- **HMAC-SHA1 from `hashlib.sha1`** — the ESP32-S3 has a hardware SHA
  engine, so CircuitPython's `hashlib` exposes `sha1`. The sample builds
  HMAC manually (inner/outer pads over `sha1`) rather than depending on
  an `hmac` module, keeping it dependency-free. On a build without
  `sha1`, it shows a clear **NO SHA1** error screen instead of crashing.
- **Hand-rolled base32 decoder** — `b32decode` implements RFC 4648
  (ignores spaces/padding) so there's no `base64` dependency either.
- **RFC 6238 core** — `T = unix // 30`, pack as 8-byte big-endian,
  HMAC, then dynamic truncation: `offset = mac[-1] & 0x0F`, take a
  31-bit int from `mac[offset..offset+3]`, mod `10^6`, zero-pad to 6.
- **Same hand-rolled NTP client as ConferenceClock** — UDP to
  `pool.ntp.org`, parse the transmit timestamp, keep a
  `monotonic ↔ unix` offset. Re-syncs hourly and on SW3.
- **No NVM** — the secret stays in source (see Configuration), which is
  also why it survives swapping to another sample and back: it's just
  sitting in `samples/TOTPAuth/code.py`.

## Notes

- Without a battery-backed RTC, the clock drifts while the badge is
  powered off, so it re-syncs over NTP on every boot. If you're offline,
  TOTP can't work (it needs accurate wall-clock time) — the error screen
  explains this.
- The test-vector secret is publicly known, so the code it produces is
  fine for demos but obviously not secure for real 2FA. Use your own
  secret (kept private) for a real account.
