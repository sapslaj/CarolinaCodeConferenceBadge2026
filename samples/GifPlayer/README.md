# GifPlayer

Plays animated GIFs full-screen on the badge, either from a `/gifs/` folder or pulled fresh off GIPHY over WiFi.

Two sources, and the first one always works:

- **LOCAL** — plays every `.gif` in `/gifs/` on the badge. No WiFi, no API key, no writing to the filesystem. This is the default, and five animations ship in `gifs/` so it does something the moment you install it.
- **GIPHY** — asks the GIPHY API for a G-rated GIF, downloads the smallest rendition, and plays it. The default tag is **`trending`**, which fetches what is popular right now — SW1 walks the top 5. The other tags roll a fresh random GIF each press.

## Controls

| Switch | Action |
|---|---|
| SW1 | Next GIF — on `trending`, steps through the top 5; on other tags, fetches a new random one |
| SW2 | Next tag (cycles `TAGS`, starting at `trending`) |
| SW3 | Switch source, LOCAL ↔ GIPHY |

## What is in `gifs/`

`gifs/` sits at the root of this repo because the repo mirrors the CIRCUITPY drive, and the badge looks for `/gifs/` on the drive.

Five original animations — `demo`, `bounce`, `spiral`, `wave`, `rain` — generated with Pillow, about 135 KB total. They exist so LOCAL mode has something to play; they are not memes. Every one is 100×100, which costs 19.5 KB of RAM per frame.

**No GIFs from GIPHY are bundled here, and you should think before adding any.** GIPHY's API is licensed for fetching and displaying GIFs at runtime, which is exactly what GIPHY mode does. Committing somebody's GIF into a repository is redistribution, which is a different thing — and most popular meme GIFs are clips from shows, films and music videos owned by studios, so the GIF being freely viewable on GIPHY does not make it yours to ship. Point `trending` at the badge instead; that is what it is for.

## Install

1. Copy `code.py` over the top-level `code.py` as usual.
2. Make sure the `gifs/` folder is at the root of the CIRCUITPY drive, so the badge has `/gifs/demo.gif`. It already lives at the root of this repo, which mirrors the drive, so a normal sync puts it in the right place.
3. For GIPHY mode, add to `settings.toml`:

```toml
WIFI_SSID     = "your-network"
WIFI_PASSWORD = "your-password"
GIPHY_API_KEY = "your-key"
```

A GIPHY key is free — create an app at [developers.giphy.com](https://developers.giphy.com/dashboard/) and copy its API key. Without one the sample still runs; SW3 just reports that the key is missing.

## The one real catch: GIPHY mode needs a writable badge

`gifio.OnDiskGif` can only open a **file**, not a buffer in memory, so a downloaded GIF has to land on the filesystem before it can be played. And CircuitPython gives write access to the filesystem to *either* the badge *or* the host computer — never both. Plugged into a laptop, the laptop usually wins, `storage.remount()` raises, and the sample says:

```
USB has the disk
eject CIRCUITPY or
run on battery
```

That is the honest answer rather than a mystery failure. Your options, easiest first:

1. **Run it on battery.** No host, no conflict, GIPHY mode just works. This is the normal way to wear the badge anyway.
2. **Eject CIRCUITPY** without unplugging (the OS keeps the board powered but drops its write claim). Behaviour here varies by OS — macOS is usually well behaved, Windows less so.
3. **Add a `boot.py`** at the drive root:

```python
import storage
storage.remount("/", readonly=False)   # badge writes, host reads
```

`boot.py` runs before USB is set up, which is the only time this is allowed unconditionally. **Read the recovery note below before you do this**, because it applies to every sample, not just this one.

### Recovering from that boot.py

With that `boot.py` in place the host can still *read* CIRCUITPY but can no longer *write* to it — which includes deleting the `boot.py` itself. To undo it, open the serial console (see [`docs/SERIAL_CONSOLE.md`](../../docs/SERIAL_CONSOLE.md)), press Ctrl-C for the REPL, and run:

```python
import storage, os
storage.remount("/", readonly=False)
os.remove("/boot.py")
```

Then reset. If you would rather not have that trapdoor at all, use battery power instead.

## Why the GIFs have to be small

`OnDiskGif` streams frames off the filesystem, so a 200-frame GIF costs no more RAM than a 5-frame one. What costs RAM is a single frame: it decodes into a `width × height × 2` byte bitmap, and this board is an ESP32-S3-WROOM-1-**N8** — 512 KB of SRAM and **no PSRAM**.

| GIF size | Frame buffer |
|---|---|
| 100×100 | 20 KB — fine |
| 128×160 (full screen) | 41 KB — fine |
| 480×270 (GIPHY default) | 259 KB — no |

`gifio` also refuses anything wider than 320 px outright. So the fetch asks for renditions in this order:

1. `fixed_width_small` — 100 px wide, the sweet spot for a 128 px screen
2. `preview_gif` — capped at 50 KB, but its dimensions are unpredictable
3. `downsized_small` — capped at 200 KB, last resort

and the download is refused outright past `MAX_BYTES` (320 KB), so a mislabelled rendition cannot fill the flash.

## Shrinking a GIF: `tools/prep_gif.py`

To put your own GIFs on the badge, run them through the included tool first. It runs on your computer (needs `pip install Pillow`), not on the badge:

```bash
python3 tools/prep_gif.py cat.gif -o gifs/cat.gif
python3 tools/prep_gif.py cat.gif --max-width 96 --colors 32 --keep-every 2
```

**The important thing it tells you is that "smaller" means two unrelated things**, and only one knob helps both:

- **RAM** is `width × height × 2` bytes for a single frame, full stop. Frame count and file size cost nothing at runtime, because `OnDiskGif` streams frames off the flash one at a time. The *only* way to reduce RAM is to make the picture smaller in pixels.
- **Flash** is the file on the drive (and the download, if it came from GIPHY). That is helped by fewer frames, fewer colours, and smaller dimensions.

Measured on a 480×270, 40-frame GIF — roughly what a GIPHY "original" looks like:

| Options | Result | Flash | RAM/frame |
|---|---|---|---|
| *(the original)* | 480×270, 40f | 174 KB | **253 KB** ✗ |
| defaults | 128×72, 40f | 112 KB | 18 KB |
| `--colors 32` | 128×72, 40f | 88 KB | 18 KB |
| `--colors 32 --keep-every 2` | 128×72, 20f | 46 KB | 18 KB |
| `--colors 32 --keep-every 3` | 128×72, 14f | 33 KB | 18 KB |
| `--max-width 96 --colors 32 --keep-every 2` | 96×54, 20f | 32 KB | 10 KB |
| `--max-width 64 --colors 32 --keep-every 2` | 64×36, 20f | 20 KB | 4.5 KB |

Read the RAM column: it does not move at all until the dimensions change, and then it moves fast — resizing to fit the panel cut it by 93% on its own. The original could not have been opened at any file size, because 480 px is past `gifio`'s 320 px limit.

Read the flash column the other way: dropping frames is the single biggest win (`--keep-every 2` roughly halves it), and reducing colours helps least. On detailed or noisy footage, palette reduction can do almost nothing at all — the file is large because of spatial detail, not colour count. If a GIF stays stubbornly big, make the picture smaller or coarser rather than reaching for `--colors`.

Rules of thumb for this badge:

- 128×160 fills the screen and costs 41 KB per frame — fine, but it is the ceiling worth aiming at.
- 100×100 (20 KB) is the comfortable default and what the bundled animations use.
- Under ~60 KB per frame is safe; past that, expect the occasional failure to open when the WiFi stack is also holding memory.

## Two details that are easy to get wrong

- **Byte order.** `gifio` hands back frames as *big-endian* RGB565; displayio expects little-endian. The `TileGrid` therefore needs `displayio.ColorConverter(input_colorspace=displayio.Colorspace.RGB565_SWAPPED)`. Get it wrong and the picture is recognisable but the colours are wild.
- **`deinit()` matters here.** The frame buffer is the largest allocation the sample makes, and on a board with no PSRAM the next GIF often cannot be opened until the previous decoder has let go. `play()` deinits in a `finally:` so this holds even when a GIF fails halfway through.

## GIPHY's terms

Using their API comes with attribution requirements, so GIPHY mode keeps a small `GIPHY` mark on screen while a fetched GIF plays. If you build on this, read [their terms](https://developers.giphy.com/docs/sdk#design-guidelines) rather than assuming that mark is sufficient for whatever you do next. The fetch also pins `rating=g`, which seems like the right default for a screen worn on your chest at a conference — it is a request to their API, though, not a guarantee about what comes back.

Each fetch rewrites one file (`/gifs/_giphy.gif`) rather than filling the drive, which also keeps flash wear to one sector's worth per GIF. It is excluded from the LOCAL list, so LOCAL means "GIFs you put there".

## Verification

The GIF-playing and GIPHY paths were tested headlessly: hardware stubbed, the filesystem sandboxed, `gifio` backed by a real Pillow GIF decoder, and a fake GIPHY API serving realistic JSON. Thirteen scenarios pass, including the ones that matter for a networked sample on a small board — no API key, an out-of-quota key returning `200` with empty data, HTTP 429, WiFi failure, a response with no usable rendition, an oversized download, a read-only filesystem, a build with no `gifio`, and an empty `/gifs/`. Trending is covered too: the endpoint used, the `limit`, and SW1 stepping through the slots. The suite also asserts that every HTTP response gets closed and every decoder gets deinited, which are the two leaks that would actually take the badge down.

What that testing cannot cover, and what is worth checking on real hardware: TLS to `api.giphy.com` is the memory high-water mark of this sample, and it happens while a frame buffer may still be allocated. If GIPHY mode fails with a memory error on a real badge, that is where to look — `MemoryError` during the fetch means dropping to `preview_gif` only, or calling `gc.collect()` more aggressively before the request.

## Code design

- **Local first, network lazily.** `wifi`, `ssl`, `socketpool` and `adafruit_requests` are imported inside `connect_wifi()`, not at the top. A badge in LOCAL mode never pays for the WiFi stack, and the sample still runs on a badge with no credentials at all.
- **Downloads are streamed.** `iter_content()` writes 1 KB at a time instead of holding the whole GIF in memory — even a 50 KB rendition is a meaningful slice of the free heap here.
- **The JSON is not kept.** The GIPHY response is several kilobytes; `giphy_random()` pulls out one URL and a title, then closes the response.
- **Errors are messages, not tracebacks.** Every failure path ends at `show_status()` with a short line for the screen and the full text on the serial console, then returns to the loop so the buttons still work. A badge that has dropped to the REPL is a brick until someone plugs it into a laptop.
