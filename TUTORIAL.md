# Your First Program on the CCC 2026 Badge

A 15-minute walkthrough — from "hello world" to lighting up LEDs, reading a button, and drawing text on the display. Everything here is specific to *this* badge and its pinout, so you can copy-paste each snippet into `code.py`, save, and watch it run.

For CircuitPython fundamentals (Python syntax, what an import does, how `while True:` loops work) the [Adafruit Learn CircuitPython Essentials](https://learn.adafruit.com/circuitpython-essentials) guide is excellent and we won't try to duplicate it here. This tutorial assumes you've read that or are comfortable with Python already.

**What you'll need**
- The badge.
- A USB-Micro cable that carries data (not a charge-only one).
- Any text editor. [Mu](https://codewith.mu) or [Thonny](https://thonny.org) are the friendliest for beginners; VS Code / Notepad++ / plain notepad all work.
- Optional but recommended: a serial console open in another window. See [`docs/SERIAL_CONSOLE.md`](docs/SERIAL_CONSOLE.md) — 5-minute setup that pays back for the whole session.

---

## 1. What you just plugged in

The badge is an **ESP32-S3 microcontroller** running **CircuitPython** — a variant of Python designed to run directly on microcontrollers. When you plug the badge into a computer over USB, three things happen:

1. **A USB drive appears**, named `CIRCUITPY`. That's the microcontroller's filesystem — everything on it is running on the badge, right now.
2. **A serial console becomes available.** `print()` output from your program, tracebacks, and the interactive REPL all live here. On Windows it's a `COM` port; on Linux/macOS it's a `/dev/tty*` device.
3. **The badge runs `code.py`** immediately on power-up, and re-runs it whenever you save changes. There is no build step, no upload button, no flash tool. Save = deploy.

Peek around the drive — you'll see:

```
CIRCUITPY/
├── code.py                 ← This is what the badge runs. Edit it.
├── settings.toml           ← Config (WiFi credentials, etc.) — os.getenv() reads it.
├── lib/                    ← Third-party libraries you can import.
├── samples/                ← Read-only samples to steal ideas from.
└── ...
```

The rest of this tutorial builds up `code.py` one concept at a time. **Before you start, back up the existing `code.py`** (rename it to `code.py.original`, or copy it somewhere off the drive) so you can restore the launcher when you're done. If you forget, `samples/Launcher/code.py` is a byte-identical backup — copy it back over `code.py` to restore.

---

## 2. Hello, world

Replace the contents of `code.py` with this:

```python
print("Hello, badge!")
```

Save the file. That's it. The badge just re-ran your program.

If you have a serial console open, you'll see `Hello, badge!` appear. If you don't, this is the moment to set one up: [`docs/SERIAL_CONSOLE.md`](docs/SERIAL_CONSOLE.md).

> **Bonus:** CircuitPython also mirrors `print()` output onto the display as a
> built-in text terminal, but *only while no program is actively driving the
> display*. In this Hello World the display isn't initialised, so you won't see
> it here. You *will* see it later when we bring up the display in section 5
> — and any time your code crashes, the traceback will appear on the LCD in
> addition to the serial console. That's a genuinely useful debugging aid
> when you don't have a serial console handy.

Now try a program that actually runs continuously:

```python
import time

count = 0
while True:
    print("Loop tick:", count)
    count += 1
    time.sleep(1)
```

Save. Watch the counter tick in your serial console once per second. Stop it with `Ctrl-C` in the REPL, or just save `code.py` again to restart from zero.

**Key thing you just learned:** `code.py` runs forever. If you want your program to keep going, wrap it in `while True:`. If it exits, CircuitPython drops you into the REPL and waits.

---

## 3. Blink the NeoPixels

The badge has **5 addressable RGB LEDs** wired to **GPIO4**. In CircuitPython you talk to them through the `neopixel` library, which is already in `lib/` — you don't need to install anything.

```python
import time
import board
import neopixel

# 5 pixels on GPIO4, dimmed to 20% brightness so you don't burn your retinas.
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.2)

while True:
    pixels.fill((255, 0, 0))   # all red
    time.sleep(0.5)
    pixels.fill((0, 255, 0))   # all green
    time.sleep(0.5)
    pixels.fill((0, 0, 255))   # all blue
    time.sleep(0.5)
```

Save. The strip cycles red → green → blue every half-second.

A few things worth knowing:
- `board.IO4` is CircuitPython's name for the GPIO4 pin. Every pin on the badge has a `board.IOn` name.
- Colors are `(R, G, B)` tuples, each 0–255.
- `brightness=0.2` scales *all* colors globally. Full brightness (1.0) draws serious current — keep it low on battery.

Want to address pixels individually? Index them like a list:

```python
import time
import board
import neopixel

pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.2, auto_write=False)

# Rainbow across the 5 pixels (fixed).
pixels[0] = (255, 0,   0  )   # red
pixels[1] = (255, 128, 0  )   # orange
pixels[2] = (0,   255, 0  )   # green
pixels[3] = (0,   0,   255)   # blue
pixels[4] = (128, 0,   255)   # purple
pixels.show()

while True:
    time.sleep(1)   # nothing to animate — just keeps code.py alive
```

Note `auto_write=False`: when you're setting several pixels at once, this avoids sending an update after every single assignment. You commit the whole frame with `pixels.show()`.

---

## 4. Read a button

The badge has **three tactile switches**:

| Switch | GPIO   |
|--------|--------|
| SW1    | GPIO1  |
| SW2    | GPIO2  |
| SW3    | GPIO43 |

They're wired to ground and rely on the ESP32's internal pull-up resistors. That means: **HIGH when idle, LOW when pressed** (active low).

```python
import time
import board
import digitalio

sw1 = digitalio.DigitalInOut(board.IO1)
sw1.direction = digitalio.Direction.INPUT
sw1.pull = digitalio.Pull.UP

while True:
    # sw1.value is False when pressed (LOW), True when idle (HIGH).
    if not sw1.value:
        print("SW1 pressed!")
    time.sleep(0.05)
```

Save. Press SW1 and watch the serial console. You'll see `SW1 pressed!` fifty times a second while held — because we're checking the level every 50 ms, not the edge.

To fire *once per press* (edge detection), track the previous state:

```python
import time
import board
import digitalio

sw1 = digitalio.DigitalInOut(board.IO1)
sw1.direction = digitalio.Direction.INPUT
sw1.pull = digitalio.Pull.UP

prev = True   # was idle last tick
while True:
    now = sw1.value
    if prev and not now:   # HIGH → LOW = press-down edge
        print("SW1 pressed!")
    prev = now
    time.sleep(0.02)
```

Now let's combine buttons and LEDs — press SW1 to light the strip red, SW2 for green, SW3 for blue:

```python
import time
import board
import digitalio
import neopixel

pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.2)

def make_button(pin):
    b = digitalio.DigitalInOut(pin)
    b.direction = digitalio.Direction.INPUT
    b.pull = digitalio.Pull.UP
    return b

sw1 = make_button(board.IO1)
sw2 = make_button(board.IO2)
sw3 = make_button(board.IO43)

while True:
    if not sw1.value:
        pixels.fill((255, 0, 0))
    elif not sw2.value:
        pixels.fill((0, 255, 0))
    elif not sw3.value:
        pixels.fill((0, 0, 255))
    else:
        pixels.fill((0, 0, 0))
    time.sleep(0.02)
```

Save. Hold each button and watch the strip change. Release everything and it goes dark.

---

## 5. Write to the display

The badge has a **160×128 pixel colour LCD** driven by the ST7735S chip on a shared SPI bus. Talking to it is a bit more work than the LEDs — there's SPI bus setup, a display driver, and CircuitPython's `displayio` graphics framework. But it's the same recipe every time; once you have it working, you can save it as a snippet and reuse it forever.

Here's the minimum program to put "HELLO" on the screen:

```python
import board
import busio
import displayio
import digitalio
import terminalio
import fourwire
import adafruit_st7735r
from adafruit_display_text import label

# --- Backlight on. GPIO5 controls the LED backlight. ---
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = True

# --- Font chip CS held HIGH so it doesn't fight the LCD on the shared SPI bus. ---
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

# --- SPI + display bus ---
displayio.release_displays()   # important! frees any previous display before re-init
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi,
    command=board.IO6,
    chip_select=board.IO10,
    reset=board.IO7,
    baudrate=8_000_000,
)

# --- Display driver ---
display = adafruit_st7735r.ST7735R(
    display_bus,
    width=128, height=160,
    rotation=0,
    bgr=True,             # the panel wires the colour channels in BGR order
    auto_refresh=False,
)

# --- Something to display ---
group = displayio.Group()
text = label.Label(terminalio.FONT, text="HELLO", color=0xFFFFFF, scale=3)
text.x = 10
text.y = 20
group.append(text)

display.root_group = group
display.refresh()

# Keep the script alive so the picture stays.
while True:
    pass
```

Save. The screen should light up with **HELLO** in white letters.

If you watched closely, you may have caught the display briefly showing a black-on-black text terminal *before* your `HELLO` appeared. That's CircuitPython's built-in terminal — once a `displayio` display exists, the OS automatically renders `print()`, tracebacks, and REPL activity onto it as a background layer. The moment you assign `display.root_group = group`, your own content replaces that terminal.

Practical consequences:
- **Your `print()` output shows on the display** whenever no user code has claimed `root_group` — including after your code exits or crashes into the REPL. This is one of the friendliest things about CircuitPython: even without a serial console, a traceback appears right on the LCD.
- **Comment out the `display.root_group = group` line** and re-save this program to see the effect: your `print()` calls will now render on the screen live.
- Samples in `/samples/` all claim `root_group`, so you won't normally see the terminal while one is running. It reappears the moment the sample exits or errors out.

The important bits:
- `displayio.release_displays()` at the top means you can re-run this over and over during editing without CircuitPython complaining about the display being already in use.
- **`rotation=0` with `width=128, height=160` is portrait.** For landscape, use `rotation=90` and swap: `width=160, height=128`.
- `auto_refresh=False` + explicit `display.refresh()` gives you frame-perfect control. If you leave it on `True`, `displayio` decides when to push pixels — usually fine, but if you're animating LEDs too you'll want the explicit version.
- `terminalio.FONT` is a built-in monospace font. For bigger, prettier fonts, load a BDF or PCF file via `adafruit_bitmap_font` (see the `Nameplate` sample for an example).

Now let's put it all together — buttons, LEDs, *and* display in one program. Press a button to change what the screen says and what colour the LEDs are:

```python
import board
import busio
import displayio
import digitalio
import terminalio
import fourwire
import adafruit_st7735r
import neopixel
from adafruit_display_text import label

# --- LEDs ---
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.2)

# --- Buttons ---
def make_button(pin):
    b = digitalio.DigitalInOut(pin)
    b.direction = digitalio.Direction.INPUT
    b.pull = digitalio.Pull.UP
    return b

sw1 = make_button(board.IO1)
sw2 = make_button(board.IO2)
sw3 = make_button(board.IO43)

# --- Display init (same as before) ---
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = True

font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7, baudrate=8_000_000
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=0, bgr=True, auto_refresh=False
)

# --- On-screen label. We'll mutate its .text and .color as buttons are pressed. ---
group = displayio.Group()
msg = label.Label(terminalio.FONT, text="press!", color=0xFFFFFF, scale=3)
msg.x = 10
msg.y = 30
group.append(msg)
display.root_group = group
display.refresh()

while True:
    if not sw1.value:
        msg.text = "RED"
        msg.color = 0xFF0000
        pixels.fill((255, 0, 0))
        display.refresh()
    elif not sw2.value:
        msg.text = "GREEN"
        msg.color = 0x00FF00
        pixels.fill((0, 255, 0))
        display.refresh()
    elif not sw3.value:
        msg.text = "BLUE"
        msg.color = 0x0000FF
        pixels.fill((0, 0, 255))
        display.refresh()
```

Save. You now have a full three-way interactive program in about 60 lines.

---

## 6. Where to go next

You've now touched every major peripheral on the badge. From here:

### Read the samples

`samples/` is a curated tour of what the badge can do. Read the `README.md` in each folder before the code — each one explains the design decisions, not just the API calls.

| Sample        | What it teaches |
|---------------|-----------------|
| `CCCLogo/`    | BMP loading with `adafruit_imageload`; PWM backlight fades. |
| `DVDBounce/`  | Simple animation loop; HSV → RGB colour math. |
| `LEDLab/`     | Decoupled patterns/palettes/speed; state machines. |
| `MorseCode/`  | Debounced input; timer-driven state machines. |
| `Nameplate/`  | Large custom fonts via `adafruit_bitmap_font`. |
| `Weather/`    | WiFi + HTTPS + JSON via `adafruit_requests`; multi-screen error handling. |
| `WiFiScanner/`| Two-scene displayio apps; `wifi.radio` scanning. |

Steal freely — that's what they're there for.

### Reference

- [`AGENTS.md`](AGENTS.md) — pin map, display init snippets, CircuitPython patterns. Written for AI coding agents, but useful for humans too — it's the fastest reference you'll find for what works on *this specific board*.
- [`README.md`](README.md) — hardware specifications, pin tables, power notes.
- [`docs/SERIAL_CONSOLE.md`](docs/SERIAL_CONSOLE.md) — everything about the serial console on every OS.

### External

- [Adafruit Learn CircuitPython Essentials](https://learn.adafruit.com/circuitpython-essentials) — the standard "learn CircuitPython" tutorial.
- [Adafruit displayio guide](https://learn.adafruit.com/circuitpython-display-support-using-displayio) — deep dive on the graphics framework.
- [CircuitPython documentation](https://docs.circuitpython.org/) — API reference for every built-in module.
- [Awesome CircuitPython](https://github.com/adafruit/awesome-circuitpython) — curated list of libraries, projects, and tutorials.

### Ideas to try

- Personalise the `Nameplate` sample with your name — change `FIRST_NAME` and `LAST_NAME` at the top of `samples/Nameplate/code.py`, copy it to `code.py`, done.
- Add a 4th LED pattern to `LEDLab`. Everything you need is one function plus a line added to `PATTERNS`.
- Use `Weather` as a starting point for something else that reads a web API — GitHub stars, sports scores, a random-quote-of-the-day. The HTTP + JSON + display pipeline is already built.
- Make a stopwatch with three buttons (start / stop / reset) and the display counting seconds.

Have fun. Break things. Save often — CircuitPython auto-reloads, so iteration is free.
