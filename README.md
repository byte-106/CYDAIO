# CYDAIO 🟡

**Cheap Yellow Display, All In One.**

One file. One import. Draw stuff on your CYD.

CYDAIO is a tiny, beginner-friendly MicroPython library for the **ESP32-2432S028R (2 USB) Cheap Yellow Display** (ILI9341 + XPT2046). No drivers to hunt down, no wiring map to copy-paste, no config maze.

> **Tested on:** ESP32-2432S028R 2USB (ILI9341 + XPT2046) with MicroPython. ✅

## Get started in 30 seconds

1. Flash MicroPython to your ESP32 CYD.
2. Copy **`cydaio.py`** onto the board (Thonny, `mpremote`, rshell — whatever you like).
3. Run this:

```python
import cydaio as cyd

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(20, 140, "Hello CYD!", cyd.WHITE, size=2)
```

That's it. You’re drawing.

## Touch paint (tiny but fun)

```python
import cydaio as cyd

cyd.init()
cyd.touch.calibrate()          # tap the 4 corners once
cyd.screen.clear(cyd.BLACK)

last = None
while True:
    cyd.update()
    if cyd.current.pressed:
        p = (cyd.current.x, cyd.current.y)
        if p != last:
            cyd.draw.pixel(p[0], p[1], cyd.WHITE)
            last = p
    else:
        last = None
```

## The stuff you'll use most

```python
cyd.init()                     # start everything
cyd.update()                   # read touch (call in your loop)

cyd.screen.clear(cyd.BLACK)
cyd.screen.brightness(80)
cyd.screen.rotation(0)         # 0, 90, 180, 270

cyd.draw.pixel(x, y, cyd.RED)
cyd.draw.line(x1, y1, x2, y2, cyd.GREEN)
cyd.draw.rect(x, y, w, h, cyd.BLUE, fill=True)
cyd.draw.circle(x, y, r, cyd.YELLOW)
cyd.draw.text(x, y, "Hi", cyd.WHITE, size=2)

cyd.touch.calibrate()          # 4-corner touch calibration
cyd.current.pressed            # True/False
cyd.current.x, cyd.current.y   # touch coords (or None)
```

## Good to know

- **Only `cydaio.py` goes on the ESP32.** Everything else in this repo is docs/examples.
- **Colors look flipped?** CYD panels often need color flipping. CYDAIO flips colors by default so things look right. Want original RGB565 values? Use `cyd.init(flip_colors=False)`.
- **Touch off?** Run `cyd.touch.calibrate()`. If calibration times out, try `cyd.touch.irq_gating(False)` before calibrating.
- **Weird edge line?** Try `cyd.screen.offset(y=1)` (or small `x/y` tweaks).
- **ST7789 CYD variant?** Not supported — this library targets the ILI9341 2USB CYD.

## More

- **[CHEATSHEET.md](CHEATSHEET.md)** — quick API lookup.
- **[REFERENCE.md](REFERENCE.md)** — full details, pin map, behavior, limits.
- **[examples/](examples/)** — `paint.py`, `shapes.py`, `screencalibrate.py`.

## License

BSD-2-Clause. See [LICENSE](LICENSE). Made for people who just want their yellow display to do the thing. 💛
