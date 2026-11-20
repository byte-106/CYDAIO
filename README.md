# CYDAIO — Cheap Yellow Display All In One

A single-file MicroPython library for the **ESP32-2432S028R (2 USB) "Cheap Yellow Display"**.

Upload one file, `cydaio.py`, call `cyd.init()`, and start drawing. There are no
driver files to copy, no pin configuration, no configuration files, and no third-party
dependencies. Everything uses MicroPython's built-in `machine`, `framebuf`, and `time`
modules.

```python
import cydaio as cyd

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(10, 10, "Hello CYD!", cyd.WHITE, size=2)

while True:
    cyd.update()
    if cyd.current.touch:
        print(cyd.current.touch)
```

## Supported hardware

Target: **ESP32-2432S028R, 2 USB revision, with an ILI9341 panel and XPT2046 resistive touch.**

| Signal | GPIO | Notes |
|---|---|---|
| Display SCK | 14 | HSPI default pins — hardware SPI |
| Display MOSI | 13 | |
| Display MISO | 12 | |
| Display CS | 15 | |
| Display DC | 2 | |
| Display RESET | — | **Not connected on this board**; software reset only |
| Backlight | 21 | PWM dimming (digital fallback) |
| Touch SCK | 25 | Separate `SoftSPI` bus |
| Touch MOSI | 32 | |
| Touch MISO | 39 | Input-only GPIO — valid for MISO |
| Touch CS | 33 | |
| Touch IRQ | 36 | Input-only GPIO; initialised, but reads are polled |

Hidden low-level details: pin map, SPI setup, ILI9341 init sequence, XPT2046
sampling, RGB565 handling, rotation mapping, and clipping.

## Installation

1. Install recent MicroPython firmware for a classic ESP32 (WROOM-32) on the board.
2. Copy **only** `cydaio.py` to the ESP32 filesystem (root directory), for example:

   ```sh
   mpremote connect /dev/ttyUSB0 fs cp cydaio.py :cydaio.py
   ```

   Thonny, rshell, or WebREPL work equally well.
3. `import cydaio as cyd` and call `cyd.init()` once at startup.

No `boot.py` or `main.py` changes are required by the library itself.

## Quick start

```python
import cydaio as cyd

cyd.init()                          # configures display, backlight and touch
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(8, 8, "Ready", cyd.WHITE)

while True:
    cyd.update()                    # refresh touch state; never blocks, no drawing
    if cyd.current.pressed:
        cyd.draw.pixel(cyd.current.x, cyd.current.y, cyd.RED)
```

## API reference

### Initialization and loop

| Call | Description |
|---|---|
| `cyd.init()` | Initialises everything. Idempotent; returns the interface object. Raises `RuntimeError` with a clear message on hardware failure. |
| `cyd.deinit()` | Turns the backlight and display off, deinitialises both SPI buses and PWM, and clears `cyd.current`. Idempotent; `init()` can be called again afterwards. |
| `cyd.update()` | Polls the touch controller once and updates `cyd.current`. Non-blocking, no display writes. |

Calling any drawing, screen, or touch method before `init()` raises `RuntimeError`.

### Colors

`cyd.BLACK`, `WHITE`, `RED`, `GREEN`, `BLUE`, `YELLOW`, `CYAN`, `MAGENTA`,
`ORANGE`, `GRAY` are predefined RGB565 values.

`cyd.rgb(r, g, b)` returns RGB565 from three integers in `0..255` (raises
`ValueError` outside that range). It is exposed at module level and also as a
method on the object returned by `cyd.init()`.

**Color inversion:** this panel requires inversion **on the display**, so the
library sends `INVON` and sets the ILI9341 `BGR` bit in `MADCTL`. `rgb()` therefore
returns ordinary RGB565 values and they appear correct on screen. Standard RGB
colors are not manually inverted in software.

### Drawing (`cyd.draw`)

All drawing operations clip to the screen; partially off-screen shapes are drawn
only in the visible region. All coordinates and dimensions must be integers and
are validated by a shared helper (non-integers raise `ValueError`). `color` must
be an integer in `0..65535`.

| Call | Description |
|---|---|
| `cyd.draw.pixel(x, y, color)` | One pixel. |
| `cyd.draw.line(x1, y1, x2, y2, color)` | Bresenham line; clipped to the viewport before rasterising, so even wildly off-screen endpoints cost at most one screen-crossing worth of work. Horizontal/vertical lines use single SPI blocks. |
| `cyd.draw.rect(x, y, width, height, color, fill=False)` | Outline or filled rectangle. Non-positive width/height draws nothing. |
| `cyd.draw.circle(x, y, radius, color, fill=False)` | Scanline circle, outline or filled. Work is bounded by the visible panel height: circles entirely off-screen, or so large that the screen lies inside them, are rejected immediately, and huge partially visible circles cost at most a few hundred row steps. |
| `cyd.draw.text(x, y, text, color, size=1)` | Built-in 8×8 font scaled by integer `size` (`1..8`); background is black. Characters outside the built-in font are skipped. |
| `cyd.draw.image(x, y, image_data)` | Blit a raw image. See format below. |

`image_data` must be a 3-tuple:

```python
(width, height, rgb565_bytes)
```

`rgb565_bytes` is row-major, two bytes per pixel, **high byte first** (the same
byte order the display expects). A `bytes`, `bytearray`, or `memoryview` object is
accepted; a memoryview is used internally so no copy is made. Example:

```python
w = h = 8
pixels = bytearray()
for y in range(h):
    for x in range(w):
        pixels.append(cyd.RED >> 8)
        pixels.append(cyd.RED & 0xFF)
cyd.draw.image(100, 100, (w, h, pixels))
```

### Screen (`cyd.screen`)

| Call / property | Description |
|---|---|
| `cyd.screen.clear(color)` | Fill the whole screen. Chunked (~1 KB) so it works without PSRAM. |
| `cyd.screen.rotation(value)` | `0`, `90`, `180`, or `270`; raises `ValueError` otherwise. Updates the panel, swaps `width`/`height`, and retargets the touch transform. Does **not** clear the screen. |
| `cyd.screen.brightness(value)` | `0..100` percent. Uses `machine.PWM` on GPIO 21; on firmware without PWM it falls back to plain on/off (a warning is printed). |
| `cyd.screen.invert(enabled=True)` | Toggle hardware color inversion (`INVON`/`INVOFF`). Default is inverted, which is correct for this panel; toggle if your panel shows reversed colors. |
| `cyd.screen.offset(x=0, y=0)` | Apply a GRAM column/page address offset to all drawing. Useful if your panel shows a fixed edge line/artifact (try small values like `y=1`). |
| `cyd.screen.width` / `cyd.screen.height` | Current logical dimensions (240×320 portrait, 320×240 landscape). |

### Touch (`cyd.touch`)

| Call | Description |
|---|---|
| `cyd.touch.read()` | Calibrated `(x, y)` in the **current rotation**, or `None` when not touched. |
| `cyd.touch.irq_gating(enabled=True)` | Enable/disable PENIRQ contact gating (enabled by default). Disable only if PENIRQ is unreliable on your panel. |
| `cyd.touch.calibrate()` | Interactive **four-point affine** calibration. First waits for the screen to be released, then draws four corner crosshairs and waits for a fresh press **and release** on each (10 s press timeout), fits a full affine transform, and erases the targets. Returns `True`. Blocking by design — do not call it from an interrupt. |

Calibration lives in RAM only: it is lost on reset. The default raw ranges
(`x: 100..1962`, `y: 100..1900`) are typical for these panels but vary per unit;
run `cyd.touch.calibrate()` once after boot if touch is offset, scaled, mirrored
or swapped. The four-corner fit solves for both native coordinates from both raw
coordinates, so it corrects axis swapping, mirroring and mild skew — not just
scale and offset. A minimum of three samples is required by `apply_calibration()`.

Contact is confirmed with the XPT2046 **PENIRQ** line (GPIO 36, active low)
before any coordinates are read. This prevents "ghost" touches caused by floating
X/Y values that happen to fall inside the raw validity range. PENIRQ is checked
only before sampling, since some panels deassert it during a conversion. If your
panel's PENIRQ is unreliable (calibration times out even while pressing), call
`cyd.touch.irq_gating(False)` before `calibrate()` to fall back to raw-range
contact detection.

### Current state (`cyd.current`)

Refreshed by `cyd.update()`:

| Attribute | Value |
|---|---|
| `cyd.current.touch` | `(x, y)` when touched, otherwise `None`. |
| `cyd.current.raw_touch` | Raw `(rx, ry)` from the XPT2046, or `None`. |
| `cyd.current.pressed` | `True` while touched. |
| `cyd.current.x` / `cyd.current.y` | Calibrated coordinates, or `None` when not touched. |

The touch values travel through two preallocated scratch lists, so no
intermediate tuples are created while reading. The cached `touch` and `raw_touch`
tuples are only rebuilt when the coordinate actually changes; a stationary finger
therefore adds no allocations per `update()` call.

## Examples

### 1. Hello World

```python
import cydaio as cyd

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(60, 150, "Hello World!", cyd.WHITE, size=2)
```

### 2. Drawing shapes

```python
import cydaio as cyd

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.pixel(10, 10, cyd.WHITE)
cyd.draw.line(0, 0, 239, 319, cyd.RED)
cyd.draw.rect(20, 30, 80, 50, cyd.GREEN)            # outline
cyd.draw.rect(110, 30, 80, 50, cyd.BLUE, fill=True)
cyd.draw.circle(120, 200, 45, cyd.YELLOW)           # outline
cyd.draw.circle(120, 200, 25, cyd.CYAN, fill=True)
cyd.draw.text(10, 290, "Shapes", cyd.MAGENTA)
```

### 3. Reading touchscreen coordinates

```python
import cydaio as cyd

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(10, 10, "Touch the screen", cyd.WHITE)

while True:
    cyd.update()
    if cyd.current.touch:
        print("screen:", cyd.current.touch,
              "raw:", cyd.current.raw_touch)
```

### 4. Simple touch button

```python
import cydaio as cyd

cyd.init()
cyd.screen.clear(cyd.BLACK)

# Button: x=60..180, y=130..190
cyd.draw.rect(60, 130, 120, 60, cyd.WHITE, fill=True)
cyd.draw.text(85, 150, "PRESS", cyd.BLACK, size=2)

pressed_last = False
while True:
    cyd.update()
    pressed_now = (cyd.current.pressed and
                   60 <= cyd.current.x <= 180 and
                   130 <= cyd.current.y <= 190)
    if pressed_now and not pressed_last:
        cyd.draw.rect(60, 130, 120, 60, cyd.GREEN, fill=True)
        cyd.draw.text(85, 150, "PRESS", cyd.BLACK, size=2)
    elif not pressed_now and pressed_last:
        cyd.draw.rect(60, 130, 120, 60, cyd.WHITE, fill=True)
        cyd.draw.text(85, 150, "PRESS", cyd.BLACK, size=2)
    pressed_last = pressed_now
```

### 5. Changing screen rotation

```python
import cydaio as cyd

cyd.init()
for rotation in (0, 90, 180, 270):
    cyd.screen.rotation(rotation)   # touch follows automatically
    cyd.screen.clear(cyd.BLACK)
    cyd.draw.text(10, 10, "Rotation %d" % rotation, cyd.WHITE, size=2)
    print(cyd.screen.width, "x", cyd.screen.height)
```

### 6. Changing brightness

```python
import cydaio as cyd

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(10, 10, "Dimming", cyd.WHITE, size=2)

for level in range(100, -1, -10):
    cyd.screen.brightness(level)
    print("brightness", level)
```

## Error handling

- `init()` failures raise `RuntimeError("cydaio: hardware init failed: ...")`.
  On failure, every resource opened so far (display SPI, backlight PWM, touch
  SPI) is released, so a subsequent `init()` can safely retry.
- `deinit()` releases the display SPI even if the panel's `DISPLAY_OFF` command
  fails; each cleanup step is attempted independently.
- Use before `init()` raises `RuntimeError`.
- Invalid rotation, brightness, color, `size`, `image_data`, or any non-integer
  drawing coordinate/dimension raises `ValueError`.
- Missing touch is reported as `None`; no exception is raised.
- Hardware errors are never silently swallowed (the only silent `except` blocks
  are in optional cleanup paths).

## Performance and memory

- No full framebuffer: a 240×320 RGB565 buffer would cost 153,600 bytes. The
  library uses a single reusable ~1 KB scratch buffer for fills, a 128-byte row
  buffer for scaled text, and tiny preallocated SPI buffers.
- Persistent Python-side buffers are roughly 1.3 KB, plus small tuples cached for
  touch state. Drawing writes directly to the panel over SPI.
- `update()` performs two short SPI transfers at 2.5 MHz (about tens of
  microseconds). It reuses preallocated scratch lists and cached result tuples,
  so it adds no allocations while the touch position is unchanged. One small
  tuple per cached state field is allocated only when coordinates change.

## Known limitations

- **No physical hardware was available for testing.** The code passed a CPython
  syntax check, a MicroPython-subset review, and a host-side stub harness covering
  colors, clipping of every primitive, all four rotations and their touch
  coordinate round-trips, brightness, current-state semantics, PENIRQ ghost-touch
  gating, calibration fitting/timeouts, and deinit/reinit. Display output, SPI
  mode, real touch accuracy, and PWM output remain **unverified on hardware**.
  Do not assume plug-and-play behaviour until tested on your board.
- No MicroPython interpreter binary was available on the development machine, so
  the code was not executed under a real MicroPython VM.
- The ST7789 2-USB variant of the CYD is **not supported**; this library targets
  the ILI9341 panel only. Some 2-USB boards shipped with ST7789 — check your panel
  before use (a white screen is the usual symptom of the wrong driver).
- Touch calibration is not persisted; there are no configuration files by design.
- The built-in text renderer is a fixed 8×8 bitmap font with integer scaling only,
  and always draws a black background behind glyphs.
- Drawing is immediate-mode: there is no framebuffer, no double buffering, and no
  anti-aliasing. Fast-moving graphics may show tearing.
- `update()` polls raw coordinates without averaging or debouncing; applications
  that need filtering should do it themselves.
- Backlight dimming depends on `machine.PWM` availability in your firmware; the
  fallback is on/off only.

## Hardware compatibility notes

- The display reset line is not connected on this board, so the library uses
  `SWRESET` and a short settle delay instead of toggling a reset GPIO.
- Display and touch use **separate SPI buses**. MISO/MOSI cannot be shared between
  them on the CYD; the display uses hardware HSPI (14/13/12) at 40 MHz and touch
  uses `SoftSPI` (25/32/39) at 2.5 MHz, mode 0.
- GPIOs 36 and 39 are input-only on the ESP32. This is correct for touch IRQ and
  MISO respectively; do not try to use them as outputs. Touch detection relies
  on PENIRQ (GPIO 36) being wired and asserted on contact, which it is on this
  board; a board without a working PENIRQ will not report touches.
- The panel needs `INVON` plus the `BGR` bit in `MADCTL` for correct colors; this is
  configured automatically and re-applied on every rotation change.
- Rotation mappings are centralized in `_XPT2046.to_native()` / `to_logical()`.
  Without calibration, raw axes are assumed to map to the native 240×320 portrait
  orientation (raw X → 240-wide axis, raw Y → 320-tall axis). Running
  `cyd.touch.calibrate()` fits an affine map that removes this assumption: swapped
  and mirrored axes, offset, scale and mild skew are corrected by the four-corner
  sample set. This is the main item still unverified on real hardware.
- Raw calibration defaults vary between panels; `cyd.touch.calibrate()` should be
  run once after boot on each unit. The fit is kept in RAM only.

## Project files

- `cydaio.py` — the complete library. **This is the only file needed on the ESP32.**
- `README.md` — this document. Examples are documentation snippets, not required files.
