# CYDAIO Cheat Sheet

Quick lookup for [CYDAIO](README.md). Full details: [REFERENCE.md](REFERENCE.md).

## Setup

```python
import cydaio as cyd

cyd.init()                      # start everything (flip_colors=True by default)
cyd.init(flip_colors=False)     # original RGB565 colors
cyd.deinit()                    # release SPI/PWM/touch/display
```

## Main loop

```python
while True:
    cyd.update()                # read touch (non-blocking)
    if cyd.current.pressed:
        x, y = cyd.current.x, cyd.current.y
```

## Screen

```python
cyd.screen.clear(cyd.BLACK)
cyd.screen.rotation(0)          # 0, 90, 180, 270
cyd.screen.brightness(80)       # 0..100
cyd.screen.invert(True)         # hardware INVON/INVOFF
cyd.screen.flip_colors(True)    # software RGB565 flip
cyd.screen.offset(x=0, y=0)     # GRAM address offset
cyd.screen.width                # 240 or 320
cyd.screen.height               # 320 or 240
```

## Draw

```python
cyd.draw.pixel(x, y, color)
cyd.draw.line(x1, y1, x2, y2, color)
cyd.draw.rect(x, y, w, h, color, fill=False)
cyd.draw.circle(x, y, r, color, fill=False)
cyd.draw.text(x, y, "Hello", color, size=1)   # size 1..8
cyd.draw.image(x, y, (w, h, rgb565_bytes))     # row-major, hi-byte first
```

## Colors

```python
cyd.BLACK, cyd.WHITE, cyd.RED, cyd.GREEN, cyd.BLUE
cyd.YELLOW, cyd.CYAN, cyd.MAGENTA, cyd.ORANGE, cyd.GRAY

cyd.rgb(255, 100, 50)           # -> RGB565 int
```

> With default `flip_colors=True`, drawn colors are software-inverted so common CYD panels look right. Use `flip_colors=False` for original RGB565.

## Touch

```python
p = cyd.touch.read()            # (x, y) or None
cyd.touch.calibrate()           # 4-corner, blocking, RAM only
cyd.touch.irq_gating(False)     # if PENIRQ is unreliable
```

## Current state (after `cyd.update()`)

```python
cyd.current.pressed             # bool
cyd.current.touch               # (x, y) or None
cyd.current.x                   # int or None
cyd.current.y                   # int or None
cyd.current.raw_touch          # (raw_x, raw_y) or None
```

## Common fixes

| Problem | Try |
|---|---|
| Touch not detected / calibration timeout | `cyd.touch.irq_gating(False)` before `calibrate()` |
| Touch offset/mirrored | `cyd.touch.calibrate()` |
| Colors look wrong | `cyd.screen.flip_colors(False)` or `cyd.screen.invert(False)` |
| 1px edge artifact | `cyd.screen.offset(y=1)` (adjust x/y) |
| White screen on boot | Confirm panel is ILI9341 (ST7789 not supported) |

## Tiny recipes

**Paint pixel:**
```python
cyd.update()
if cyd.current.pressed:
    cyd.draw.pixel(cyd.current.x, cyd.current.y, cyd.WHITE)
```

**Button hit:**
```python
cyd.update()
if cyd.current.pressed and 60 <= cyd.current.x <= 180 and 130 <= cyd.current.y <= 190:
    print("pressed!")
```

**Custom color:**
```python
purple = cyd.rgb(128, 0, 255)
cyd.draw.rect(10, 10, 50, 30, purple, fill=True)
```