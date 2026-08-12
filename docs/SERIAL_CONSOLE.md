# Viewing the CircuitPython Serial Console

CircuitPython prints all `print()` output, tracebacks, and REPL prompts over
a USB serial (CDC) connection. To see them you need:

1. A terminal program that can open the serial device.
2. The correct device name (`COMx` on Windows, `/dev/ttyACM*` on Linux,
   `/dev/tty.usbmodem*` or `/dev/cu.usbmodem*` on macOS).
3. **DTR asserted** on the connection — this is a gotcha with the ESP32-S3's
   native USB. Without it the port opens but stays silent. Most GUI
   terminals do this for you; custom scripts must set it explicitly.

---

## 1. Find the serial device

The conference board uses the Adafruit CircuitPython build for the ESP32-S3-DevKitC-1-N8 which is made for the Espressif ESP32-S3-WROOM-1-N8 chip used on the badge. Espressif's USB vendor ID is
`303A`. That's the fingerprint to look for.

### Windows

**PowerShell:**

```powershell
Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.DeviceID -match 'VID_303A' -and $_.Name -match 'COM' } |
  Select-Object Name
```

Example output:

```
Name
----
USB Serial Device (COM7)
```

**Device Manager:** expand *Ports (COM & LPT)*, look for the entry that
appears and disappears when you unplug/replug the board.

### Linux

The board enumerates as a CDC ACM device, typically `/dev/ttyACM0` (the
number increments if other CDC devices are present).

```bash
ls /dev/ttyACM*
```

Confirm it's the badge by checking the vendor ID:

```bash
lsusb | grep -i 303a
# or, to see the specific tty:
for d in /dev/ttyACM*; do
  udevadm info -q property -n "$d" | grep -E 'ID_VENDOR_ID|ID_MODEL'
done
```

`dmesg | tail` right after plugging in also shows which `ttyACM*` was
just assigned.

**Permissions:** on most distros the serial device is owned by the
`dialout` group (or `uucp` on Arch). If you get `Permission denied`
opening the port, add yourself to that group and log out/in:

```bash
sudo usermod -aG dialout $USER   # Debian/Ubuntu/Fedora
sudo usermod -aG uucp    $USER   # Arch
```

### macOS

The board enumerates under two names — use the `cu.*` variant for
interactive terminals:

```bash
ls /dev/cu.usbmodem*
# example: /dev/cu.usbmodem14201
```

Confirm it's the badge:

```bash
system_profiler SPUSBDataType | grep -A 4 -i 'espressif\|303a'
```

No driver install is required on macOS 11+ — the built-in CDC driver
handles it. If nothing appears, try a different USB-C cable (many
charge-only cables lack data lines).


## 2. Pick a terminal

| Tool | Platforms | Recommended for | Notes |
|---|---|---|---|
| **[Mu Editor](https://codewith.mu)** | Win / mac / Linux | Workshops / beginners | Auto-detects CircuitPython boards. One-click **Serial** button, no config. Also ships a plotter. |
| **[Thonny](https://thonny.org)** | Win / mac / Linux | Python learners | Full IDE with built-in REPL and file transfer. |
| **PuTTY / Tera Term** | Windows | Traditionalists | Configure "Serial", COMx, 115200 baud. In PuTTY, also enable *Terminal → Implicit CR in every LF* for cleaner line breaks. |
| **VS Code + "Serial Monitor" extension** | Win / mac / Linux | Existing VS Code users | Search the extension marketplace for `ms-vscode.vscode-serial-monitor`. |
| **`screen`** | mac / Linux | Zero-install CLI | `screen /dev/ttyACM0 115200` (Linux) or `screen /dev/cu.usbmodem14201 115200` (macOS). Exit with `Ctrl-A` then `K` then `y`. |
| **[`tio`](https://github.com/tio/tio)** | mac / Linux | Best CLI experience | `tio /dev/ttyACM0`. Auto-reconnects if you unplug/replug — very handy when iterating. Install via `apt`, `dnf`, or `brew`. |
| **`minicom`** | mac / Linux | Traditionalists | `minicom -D /dev/ttyACM0 -b 115200`. First run: `minicom -s` to disable hardware flow control. |
| **`pyserial` miniterm** | Any | Already have Python | `python3 -m serial.tools.miniterm /dev/ttyACM0 115200` (or `COM7` on Windows). Exit with `Ctrl-]`. |

Baud rate: any value works (USB CDC ignores baud), but `115200` is the convention.


## 3. Zero-install: read the console from the shell

Handy for quick checks when you don't want to install anything. Adjust the
device name to whatever you found in step 1.

### Windows (PowerShell)

**The `DtrEnable = $true` line is essential** — see the note below.

```powershell
$p = New-Object System.IO.Ports.SerialPort 'COM7', 115200
$p.DtrEnable = $true
$p.Open()
while ($true) {
    Write-Host -NoNewline $p.ReadExisting()
    Start-Sleep -Milliseconds 100
}
```

Stop with `Ctrl-C`.

### Linux / macOS

`screen` is preinstalled on macOS and most Linux distros and asserts DTR
automatically:

```bash
# Linux
screen /dev/ttyACM0 115200

# macOS
screen /dev/cu.usbmodem14201 115200
```

Exit with `Ctrl-A` then `K` then `y`. If `screen` says the device is busy,
another terminal already owns it — close the other one first.

No `screen`? Every macOS and most Linux systems ship Python 3, and
CircuitPython's tooling comes with `pyserial`:

```bash
python3 -m serial.tools.miniterm /dev/ttyACM0 115200   # Linux
python3 -m serial.tools.miniterm /dev/cu.usbmodem14201 115200   # macOS
```

Exit `miniterm` with `Ctrl-]`.

### Soft-reset the board and capture the boot output

Useful when you want to re-run `code.py` from the top and see everything it
prints. `0x03` is Ctrl-C (interrupt any running code), `0x04` is Ctrl-D (soft
reset).

**Windows (PowerShell):**

```powershell
$p = New-Object System.IO.Ports.SerialPort 'COM7', 115200
$p.DtrEnable = $true
$p.ReadTimeout = 300
$p.Open()
Start-Sleep -Milliseconds 400
$p.Write([byte[]]@(0x03), 0, 1)   # Ctrl-C -- interrupt
Start-Sleep -Milliseconds 300
$p.Write([byte[]]@(0x04), 0, 1)   # Ctrl-D -- soft reboot
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    Write-Host -NoNewline $p.ReadExisting()
    Start-Sleep -Milliseconds 100
}
$p.Close()
```

**Linux / macOS (bash + python):**

```bash
PORT=/dev/ttyACM0   # or /dev/cu.usbmodem14201 on macOS
python3 - <<'PY'
import os, time, serial
port = os.environ["PORT"]
p = serial.Serial(port, 115200, timeout=0.3)
p.dtr = True
time.sleep(0.4)
p.write(b'\x03')     # Ctrl-C -- interrupt
time.sleep(0.3)
p.write(b'\x04')     # Ctrl-D -- soft reboot
deadline = time.time() + 20
while time.time() < deadline:
    data = p.read(4096)
    if data:
        print(data.decode(errors="replace"), end="", flush=True)
p.close()
PY
```

Inside an interactive `screen` or `tio` session you can do the same manually:
press `Ctrl-C` to interrupt, then `Ctrl-D` to soft-reboot.



## The DTR gotcha (why the console can appear "dead")

The ESP32-S3 uses its own native USB stack (no CP2102 / FT232 bridge chip in
the middle). CircuitPython's CDC endpoint only starts sending data once the
host signals it's ready to receive by asserting **DTR** (Data Terminal
Ready).

Traditional terminals (Mu, Thonny, PuTTY, `screen`, `minicom`, `tio`) do
this automatically. But if you open the port from a custom script, the port
opens successfully, no error is raised — and you see nothing. Every byte
from the board is queued but never delivered.

Set DTR explicitly in your code:

| Language / tool | Line to add |
|---|---|
| PowerShell `System.IO.Ports.SerialPort` | `$p.DtrEnable = $true` |
| Python `pyserial` | `ser.dtr = True` (or pass `dsrdtr=False` on construction, then set) |
| Node `serialport` | `port.set({ dtr: true })` |
| C `termios` (Linux/macOS) | `int b = TIOCM_DTR; ioctl(fd, TIOCMBIS, &b);` — and open the tty *without* `O_NONBLOCK`/`O_NDELAY`, which suppresses the modem-line assert. |

If a terminal ever looks unresponsive, DTR is the first thing to check.



## Auto-reload

CircuitPython watches the filesystem. Saving `code.py` (or any imported
module) triggers a soft reboot and re-runs your code automatically — you
don't need to press RESET. Watch the serial console to see the fresh run.

To disable auto-reload for a session, connect to the REPL and run:

```python
import supervisor
supervisor.runtime.autoreload = False
```



## Common REPL keys

| Key | Effect |
|---|---|
| `Ctrl-C` | Interrupt the running program, drop into REPL |
| `Ctrl-D` | Soft reboot (re-runs `code.py`) |
| `Ctrl-E` | Enter **paste mode** — bulk-paste code without auto-indent |
| `Ctrl-B` | Exit REPL back to running `code.py` |
| Any key | Wake the REPL when it shows *Press any key to enter the REPL* |
