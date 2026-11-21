"""CYDAIO - all-in-one MicroPython library for the ESP32 Cheap Yellow Display.

Target hardware: ESP32-2432S028R (2 USB), ILI9341 240x320, XPT2046 resistive
touch.  This is the only file you need to upload to the ESP32 filesystem.

    import cydaio as cyd
    cyd.init()
    cyd.screen.clear(cyd.BLACK)
    cyd.draw.text(10, 10, "Hello!", cyd.WHITE)

Everything is in one file by design.  The internal classes below are private
(prefixed with "_"); only the module-level objects and constants are public.
"""

from machine import Pin, SPI, SoftSPI  # type: ignore
from time import sleep, sleep_ms, ticks_ms, ticks_diff  # type: ignore
from micropython import const  # type: ignore
from framebuf import FrameBuffer, MONO_HLSB  # type: ignore
from math import sqrt  # type: ignore

try:
    from machine import PWM  # type: ignore
except ImportError:
    PWM = None


# ---------------------------------------------------------------------------
# Central hardware configuration (ESP32-2432S028R, 2 USB)
# ---------------------------------------------------------------------------

_TFT_SCK = const(14)
_TFT_MOSI = const(13)
_TFT_MISO = const(12)
_TFT_CS = const(15)
_TFT_DC = const(2)
_TFT_BL = const(21)

_TOUCH_SCK = const(25)
_TOUCH_MOSI = const(32)
_TOUCH_MISO = const(39)   # input-only GPIO, fine for MISO
_TOUCH_CS = const(33)
_TOUCH_IRQ = const(36)    # input-only GPIO; initialised but polling is used

_PANEL_W = const(240)
_PANEL_H = const(320)
_TFT_BAUD = const(40000000)
_TOUCH_BAUD = const(2500000)
_SCRATCH = const(1024)

# MADCTL values for rotations 0, 90, 180, 270.  The BGR bit (0x08) is ORed in
# by the driver: this panel needs BGR order and inversion for correct colours.
_MADCTL = (0x80, 0xE0, 0x40, 0x20)


# ---------------------------------------------------------------------------
# Colours and small validation helpers
# ---------------------------------------------------------------------------

BLACK = const(0x0000)
WHITE = const(0xFFFF)
RED = const(0xF800)
GREEN = const(0x07E0)
BLUE = const(0x001F)
YELLOW = const(0xFFE0)
CYAN = const(0x07FF)
MAGENTA = const(0xF81F)
ORANGE = const(0xFD20)
GRAY = const(0x8410)


def _rgb(r, g, b):
    """Return a standard RGB565 value from three 0-255 components.

    The panel itself is configured for BGR order and hardware inversion, so
    standard RGB values produce the expected colours on screen.
    """
    if not isinstance(r, int) or not isinstance(g, int) or not isinstance(b, int):
        raise ValueError("rgb() components must be integers")
    if r < 0 or r > 255 or g < 0 or g > 255 or b < 0 or b > 255:
        raise ValueError("rgb() components must be in 0..255")
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


# Public module-level alias: cyd.rgb(r, g, b)
rgb = _rgb


def _check_color(color):
    if not isinstance(color, int) or color < 0 or color > 0xFFFF:
        raise ValueError("color must be an integer in 0..65535")


def _check_int(name, value):
    """Unified integer validation for all coordinates and dimensions."""
    if not isinstance(value, int):
        raise ValueError("%s must be an integer" % name)


def _check_xy(x, y):
    _check_int("x", x)
    _check_int("y", y)


def _check_rotation(value):
    if not isinstance(value, int) or value not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180 or 270")


def _clip_line(x1, y1, x2, y2, w, h):
    """Liang-Barsky clip; returns clipped endpoints or None if invisible."""
    dx = x2 - x1
    dy = y2 - y1
    t0 = 0.0
    t1 = 1.0
    edges = ((-dx, x1), (dx, w - 1 - x1), (-dy, y1), (dy, h - 1 - y1))
    for p, q in edges:
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    ax = int(x1 + t0 * dx)
    ay = int(y1 + t0 * dy)
    bx = int(x1 + t1 * dx)
    by = int(y1 + t1 * dy)
    # Guard against floating-point round-off at the boundaries.
    if ax < 0:
        ax = 0
    elif ax >= w:
        ax = w - 1
    if ay < 0:
        ay = 0
    elif ay >= h:
        ay = h - 1
    if bx < 0:
        bx = 0
    elif bx >= w:
        bx = w - 1
    if by < 0:
        by = 0
    elif by >= h:
        by = h - 1
    return (ax, ay, bx, by)


def _solve3(matrix, vector):
    """Solve a 3x3 linear system by Gaussian elimination with pivoting."""
    a = [list(matrix[0]), list(matrix[1]), list(matrix[2])]
    b = [vector[0], vector[1], vector[2]]
    for col in range(3):
        pivot = col
        best = abs(a[col][col])
        for row in range(col + 1, 3):
            value = abs(a[row][col])
            if value > best:
                best = value
                pivot = row
        if best < 1e-12:
            raise ValueError("calibration points do not define a valid transform")
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            b[col], b[pivot] = b[pivot], b[col]
        for row in range(col + 1, 3):
            factor = a[row][col] / a[col][col]
            if factor == 0:
                continue
            for c in range(col, 3):
                a[row][c] -= factor * a[col][c]
            b[row] -= factor * b[col]
    result = [0.0, 0.0, 0.0]
    for row in range(2, -1, -1):
        total = b[row]
        for c in range(row + 1, 3):
            total -= a[row][c] * result[c]
        result[row] = total / a[row][row]
    return result


# ---------------------------------------------------------------------------
# Internal ILI9341 driver
# ---------------------------------------------------------------------------

class _ILI9341:
    """Minimal ILI9341 SPI driver with no framebuffer allocation."""

    SWRESET = const(0x01)
    SLPOUT = const(0x11)
    INVOFF = const(0x20)
    INVON = const(0x21)
    VSCRDEF = const(0x33)
    VSCRSADD = const(0x37)
    DISPLAY_OFF = const(0x28)
    DISPLAY_ON = const(0x29)
    SET_COLUMN = const(0x2A)
    SET_PAGE = const(0x2B)
    WRITE_RAM = const(0x2C)
    MADCTL = const(0x36)
    PIXFMT = const(0x3A)
    GAMMASET = const(0x26)
    FRMCTR1 = const(0xB1)
    DFUNCTR = const(0xB6)
    PWCTR1 = const(0xC0)
    PWCTR2 = const(0xC1)
    PWCTRA = const(0xCB)
    PWCTRB = const(0xCF)
    VMCTR1 = const(0xC5)
    VMCTR2 = const(0xC7)
    GMCTRP1 = const(0xE0)
    GMCTRN1 = const(0xE1)
    DTCA = const(0xE8)
    DTCB = const(0xEA)
    POSC = const(0xED)
    ENABLE3G = const(0xF2)
    PUMPRC = const(0xF7)

    def __init__(self):
        self.spi = None
        # HSPI defaults are exactly SCK=14, MOSI=13, MISO=12 on ESP32.
        # Some firmware versions reject pin kwargs for fixed SPI hosts; the
        # defaults are identical, so falling back to id-only is safe.
        try:
            try:
                self.spi = SPI(1, _TFT_BAUD, polarity=0, phase=0,
                               sck=Pin(_TFT_SCK), mosi=Pin(_TFT_MOSI),
                               miso=Pin(_TFT_MISO))
            except (TypeError, ValueError) as exc:
                print("cydaio: using default HSPI pins:", exc)
                self.spi = SPI(1, _TFT_BAUD, polarity=0, phase=0)
            self.cs = Pin(_TFT_CS, Pin.OUT, value=1)
            self.dc = Pin(_TFT_DC, Pin.OUT, value=0)
            self._one = bytearray(1)
            self._addr = bytearray(4)
            self.rotation = 0
            self.width = _PANEL_W
            self.height = _PANEL_H
            self.x_offset = 0
            self.y_offset = 0
            self.inverted = True
            self._init_panel()
        except Exception:
            # Never leave an open SPI bus behind on partial init.
            if self.spi is not None:
                try:
                    self.spi.deinit()
                except Exception:
                    pass
                self.spi = None
            raise

    def _cmd(self, command, data=None):
        """Write one command, optionally followed by data in the same CS window."""
        self._one[0] = command
        self.cs(0)
        self.dc(0)
        self.spi.write(self._one)
        if data is not None:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _init_panel(self):
        # No hardware reset pin on this board: the panel reset is tied high.
        sleep(0.05)
        self._cmd(self.SWRESET)
        sleep(0.10)
        self._cmd(self.PWCTRB, bytearray((0x00, 0xC1, 0x30)))
        self._cmd(self.POSC, bytearray((0x64, 0x03, 0x12, 0x81)))
        self._cmd(self.DTCA, bytearray((0x85, 0x00, 0x78)))
        self._cmd(self.PWCTRA, bytearray((0x39, 0x2C, 0x00, 0x34, 0x02)))
        self._cmd(self.PUMPRC, bytearray((0x20,)))
        self._cmd(self.DTCB, bytearray((0x00, 0x00)))
        self._cmd(self.PWCTR1, bytearray((0x23,)))
        self._cmd(self.PWCTR2, bytearray((0x10,)))
        self._cmd(self.VMCTR1, bytearray((0x3E, 0x28)))
        self._cmd(self.VMCTR2, bytearray((0x86,)))
        self._cmd(self.MADCTL, bytearray((_MADCTL[0] | 0x08,)))
        self._cmd(self.PIXFMT, bytearray((0x55,)))
        self._cmd(self.FRMCTR1, bytearray((0x00, 0x18)))
        self._cmd(self.DFUNCTR, bytearray((0x08, 0x82, 0x27)))
        self._cmd(self.ENABLE3G, bytearray((0x00,)))
        self._cmd(self.GAMMASET, bytearray((0x01,)))
        self._cmd(self.GMCTRP1, bytearray((0x0F, 0x31, 0x2B, 0x0C, 0x0E, 0x08,
                                          0x4E, 0xF1, 0x37, 0x07, 0x10, 0x03,
                                          0x0E, 0x09, 0x00)))
        self._cmd(self.GMCTRN1, bytearray((0x00, 0x0E, 0x14, 0x03, 0x11, 0x07,
                                          0x31, 0xC1, 0x48, 0x08, 0x0F, 0x0C,
                                          0x31, 0x36, 0x0F)))
        # Reset vertical scroll: full 320-line area, no scroll offset.
        self._cmd(self.VSCRDEF, bytearray((0x00, 0x00, 0x01, 0x40, 0x00, 0x00)))
        self._cmd(self.VSCRSADD, bytearray((0x00, 0x00)))
        self._cmd(self.INVON if self.inverted else self.INVOFF)
        self._cmd(self.SLPOUT)
        sleep(0.10)
        self._cmd(self.DISPLAY_ON)
        sleep(0.10)

    def set_rotation(self, value):
        self.rotation = value
        self._cmd(self.MADCTL, bytearray((_MADCTL[value // 90] | 0x08,)))
        if value == 0 or value == 180:
            self.width = _PANEL_W
            self.height = _PANEL_H
        else:
            self.width = _PANEL_H
            self.height = _PANEL_W

    def set_invert(self, enabled):
        self.inverted = bool(enabled)
        self._cmd(self.INVON if self.inverted else self.INVOFF)

    def set_offset(self, x=0, y=0):
        self.x_offset = int(x)
        self.y_offset = int(y)

    def block(self, x0, y0, x1, y1, data):
        """Write a clipped, row-major RGB565 byte buffer to the given window."""
        ox = self.x_offset
        oy = self.y_offset
        a = self._addr
        cx0 = x0 + ox
        cx1 = x1 + ox
        cy0 = y0 + oy
        cy1 = y1 + oy
        if cx0 < 0:
            cx0 = 0
        if cx1 < 0:
            cx1 = 0
        if cy0 < 0:
            cy0 = 0
        if cy1 < 0:
            cy1 = 0
        a[0] = (cx0 >> 8) & 0xFF
        a[1] = cx0 & 0xFF
        a[2] = (cx1 >> 8) & 0xFF
        a[3] = cx1 & 0xFF
        self._cmd(self.SET_COLUMN, a)
        a[0] = (cy0 >> 8) & 0xFF
        a[1] = cy0 & 0xFF
        a[2] = (cy1 >> 8) & 0xFF
        a[3] = cy1 & 0xFF
        self._cmd(self.SET_PAGE, a)
        self._cmd(self.WRITE_RAM, data)

    def deinit(self):
        # Independent blocks: a failed DISPLAY_OFF must not prevent the SPI bus
        # from being released.
        try:
            self._cmd(self.DISPLAY_OFF)
        except Exception:
            pass
        try:
            if self.spi is not None:
                self.spi.deinit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Internal XPT2046 driver
# ---------------------------------------------------------------------------

class _XPT2046:
    """Raw sampling, calibration coefficients and rotation mapping."""

    GET_X = const(0xD0)
    GET_Y = const(0x90)

    def __init__(self):
        self.spi = None
        try:
            self.spi = SoftSPI(baudrate=_TOUCH_BAUD, polarity=0, phase=0,
                               sck=Pin(_TOUCH_SCK), mosi=Pin(_TOUCH_MOSI),
                               miso=Pin(_TOUCH_MISO))
            self.cs = Pin(_TOUCH_CS, Pin.OUT, value=1)
            self.irq = Pin(_TOUCH_IRQ, Pin.IN)  # PENIRQ contact signal
        except Exception:
            if self.spi is not None:
                try:
                    self.spi.deinit()
                except Exception:
                    pass
                self.spi = None
            raise
        self._tx = bytearray(3)
        self._rx = bytearray(3)
        # PENIRQ can be checked before sampling.  Some panels/firmware report
        # it unreliable; touch.irq_gating(False) disables that check.
        self.irq_enabled = True
        # Typical raw ranges for this panel; run touch.calibrate() to replace.
        self.x_min = 100
        self.x_max = 1962
        self.y_min = 100
        self.y_max = 1900
        # Affine transform fitted by apply_calibration():
        #   native_x = ax*raw_x + bx*raw_y + cx
        #   native_y = ay*raw_x + by*raw_y + cy
        # This handles scale, offset, axis swap, mirroring and mild skew.
        self.ax = 1.0
        self.bx = 0.0
        self.cx = 0.0
        self.ay = 0.0
        self.by = 1.0
        self.cy = 0.0
        self.calibrated = False
        self.rotation = 0
        self._rx_raw = 0
        self._ry_raw = 0
        self._raw_cache = None
        self._point = None
        self._px = 0
        self._py = 0
        # Preallocated scratch for the read() hot path: no intermediate tuples.
        self._native_out = [0, 0]
        self._logical_out = [0, 0]

    @property
    def last_raw(self):
        """Cached (raw_x, raw_y) tuple, or None when not touched."""
        return self._raw_cache

    def _sample(self, command):
        tx = self._tx
        rx = self._rx
        tx[0] = command
        tx[1] = 0
        tx[2] = 0
        self.cs(0)
        self.spi.write_readinto(tx, rx)
        self.cs(1)
        return (rx[1] << 4) | (rx[2] >> 4)

    def raw(self):
        """Return a cached raw (x, y) tuple when touched, otherwise None.

        PENIRQ (GPIO 36) is active low. It is checked *before* sampling only:
        some XPT2046 units deassert PENIRQ while a conversion is in progress,
        so checking it again afterwards would reject genuine touches. Floating
        coordinates are still rejected by the raw-range check below.
        """
        if self.irq_enabled and self.irq.value():  # high means no pen contact
            self._raw_cache = None
            return None
        x = self._sample(self.GET_X)
        y = self._sample(self.GET_Y)
        if self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max:
            if x != self._rx_raw or y != self._ry_raw or self._raw_cache is None:
                self._rx_raw = x
                self._ry_raw = y
                self._raw_cache = (x, y)
        else:
            self._raw_cache = None
        return self._raw_cache

    def set_rotation(self, value):
        self.rotation = value
        self._point = None

    def to_native(self, x, y, rotation, out=None):
        """Logical (x, y) -> native portrait coordinates.

        When ``out`` is a two-element mutable sequence it is filled and
        returned instead of allocating a tuple (used by the read hot path).
        """
        if rotation == 0:
            nx, ny = x, y
        elif rotation == 90:
            nx, ny = y, _PANEL_H - 1 - x
        elif rotation == 180:
            nx, ny = _PANEL_W - 1 - x, _PANEL_H - 1 - y
        else:
            nx, ny = _PANEL_W - 1 - y, x
        if out is None:
            return nx, ny
        out[0] = nx
        out[1] = ny
        return out

    def to_logical(self, nx, ny, rotation, out=None):
        """Native portrait coordinates -> logical (x, y); ``out`` optional."""
        if rotation == 0:
            x, y = nx, ny
        elif rotation == 90:
            x, y = _PANEL_H - 1 - ny, nx
        elif rotation == 180:
            x, y = _PANEL_W - 1 - nx, _PANEL_H - 1 - ny
        else:
            x, y = ny, _PANEL_W - 1 - nx
        if out is None:
            return x, y
        out[0] = x
        out[1] = y
        return out

    def _native_from_raw(self, rx, ry, out=None):
        """Raw -> native portrait coordinates; ``out`` optional.

        The uncalibrated default matches the common ESP32-2432S028R 2USB
        XPT2046 mounting: raw X maps to native X, raw Y is inverted to native Y.
        A 4-point ``apply_calibration()`` fit overrides this with a full affine
        map and is recommended for panel-to-panel variance.
        """
        if self.calibrated:
            nx = self.ax * rx + self.bx * ry + self.cx
            ny = self.ay * rx + self.by * ry + self.cy
        else:
            nx = (rx - self.x_min) * (_PANEL_W - 1) / (self.x_max - self.x_min)
            ny = (self.y_max - ry) * (_PANEL_H - 1) / (self.y_max - self.y_min)
        if nx < 0:
            nx = 0
        elif nx > _PANEL_W - 1:
            nx = _PANEL_W - 1
        if ny < 0:
            ny = 0
        elif ny > _PANEL_H - 1:
            ny = _PANEL_H - 1
        ix = int(nx)
        iy = int(ny)
        if out is None:
            return ix, iy
        out[0] = ix
        out[1] = iy
        return out

    def read(self):
        """Return a cached calibrated point in current rotation space.

        Intermediate coordinates go into preallocated lists; the only tuple
        created is the cached result, and only when the position changes.
        """
        raw = self.raw()
        if raw is None:
            self._point = None
            return None
        native = self._native_out
        self._native_from_raw(raw[0], raw[1], native)
        logical = self._logical_out
        self.to_logical(native[0], native[1], self.rotation, logical)
        x = logical[0]
        y = logical[1]
        if self._point is None or x != self._px or y != self._py:
            self._px = x
            self._py = y
            self._point = (x, y)
        return self._point

    def apply_calibration(self, samples):
        """Fit a full 2-D affine map from at least three (rx, ry, nx, ny) points.

        Least squares over all samples solves the 3x3 normal equations twice.
        Unlike an independent per-axis scale/offset fit this corrects axis
        swapping, mirroring and skew, because each native coordinate depends on
        both raw coordinates.  Four corner samples are used by calibrate().
        """
        if len(samples) < 3:
            raise ValueError("calibration needs at least three samples")
        sxx = sxy = syy = sx = sy = 0.0
        srx_nx = sry_nx = snx = 0.0
        srx_ny = sry_ny = sny = 0.0
        lo_rx = lo_ry = 4096
        hi_rx = hi_ry = 0
        for sample in samples:
            rx = sample[0]
            ry = sample[1]
            nx = sample[2]
            ny = sample[3]
            sxx += rx * rx
            sxy += rx * ry
            syy += ry * ry
            sx += rx
            sy += ry
            srx_nx += rx * nx
            sry_nx += ry * nx
            snx += nx
            srx_ny += rx * ny
            sry_ny += ry * ny
            sny += ny
            if rx < lo_rx:
                lo_rx = rx
            if rx > hi_rx:
                hi_rx = rx
            if ry < lo_ry:
                lo_ry = ry
            if ry > hi_ry:
                hi_ry = ry
        matrix = ((sxx, sxy, sx), (sxy, syy, sy), (sx, sy, len(samples)))
        self.ax, self.bx, self.cx = _solve3(matrix, (srx_nx, sry_nx, snx))
        self.ay, self.by, self.cy = _solve3(matrix, (srx_ny, sry_ny, sny))
        self.calibrated = True
        # Generous raw validity bounds from the sampled raw range.
        mx = max(20, int((hi_rx - lo_rx) * 0.10))
        my = max(20, int((hi_ry - lo_ry) * 0.10))
        self.x_min = lo_rx - mx
        self.x_max = hi_rx + mx
        self.y_min = lo_ry - my
        self.y_max = hi_ry + my
        self._point = None

    def deinit(self):
        try:
            self.spi.deinit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Drawing API
# ---------------------------------------------------------------------------

class _Draw:
    """Clipped drawing primitives.  No full-screen buffer is ever allocated."""

    def __init__(self, host):
        self._host = host
        self._pair = bytearray(2)
        self._scratch = bytearray(_SCRATCH)
        self._fill_mv = memoryview(self._scratch)
        self._glyph_buf = bytearray(8)
        self._glyph = FrameBuffer(self._glyph_buf, 8, 8, MONO_HLSB)
        self._text_row = bytearray(8 * 8 * 2)
        self._text_mv = memoryview(self._text_row)

    def _dev(self):
        self._host._require()
        return self._host._device

    def _set_pair(self, color):
        self._pair[0] = color >> 8
        self._pair[1] = color & 0xFF

    def _repeat(self, color, count):
        """Fill scratch with `count` RGB565 pixels and return a memoryview.

        MicroPython does not support ``bytearray * int`` (unlike CPython), so
        all repeated pixel data is built explicitly in the scratch buffer.
        """
        n = count * 2
        if n > _SCRATCH:
            n = _SCRATCH
        hi = color >> 8
        lo = color & 0xFF
        buf = self._scratch
        for i in range(0, n, 2):
            buf[i] = hi
            buf[i + 1] = lo
        return self._fill_mv[:n]

    def _point(self, dev, x, y, color):
        if x < 0 or y < 0 or x >= dev.width or y >= dev.height:
            return
        self._set_pair(color)
        dev.block(x, y, x, y, self._pair)

    def _hline(self, dev, x, y, w, color):
        if w <= 0 or y < 0 or y >= dev.height:
            return
        x0 = x
        x1 = x + w - 1
        if x1 < 0 or x0 >= dev.width:
            return
        if x0 < 0:
            x0 = 0
        if x1 >= dev.width:
            x1 = dev.width - 1
        dev.block(x0, y, x1, y, self._repeat(color, x1 - x0 + 1))

    def _vline(self, dev, x, y, h, color):
        if h <= 0 or x < 0 or x >= dev.width:
            return
        y0 = y
        y1 = y + h - 1
        if y1 < 0 or y0 >= dev.height:
            return
        if y0 < 0:
            y0 = 0
        if y1 >= dev.height:
            y1 = dev.height - 1
        dev.block(x, y0, x, y1, self._repeat(color, y1 - y0 + 1))

    def _fill(self, dev, x0, y0, x1, y1, color):
        """Clipped rectangle fill in chunks of at most _SCRATCH bytes."""
        if x1 < x0 or y1 < y0:
            return
        if x0 < 0:
            x0 = 0
        if y0 < 0:
            y0 = 0
        if x1 >= dev.width:
            x1 = dev.width - 1
        if y1 >= dev.height:
            y1 = dev.height - 1
        if x1 < x0 or y1 < y0:
            return
        w = x1 - x0 + 1
        rows = _SCRATCH // (w * 2)
        if rows < 1:
            rows = 1
        self._repeat(color, w * rows)
        mv = self._fill_mv
        y = y0
        while y <= y1:
            nr = rows
            if y + nr - 1 > y1:
                nr = y1 - y + 1
            dev.block(x0, y, x1, y + nr - 1, mv[:w * nr * 2])
            y += nr

    def _color(self, color):
        _check_color(color)
        if self._host.flip_colors:
            return color ^ 0xFFFF
        return color

    # -- public primitives -------------------------------------------------

    def pixel(self, x, y, color):
        color = self._color(color)
        _check_xy(x, y)
        self._point(self._dev(), x, y, color)

    def line(self, x1, y1, x2, y2, color):
        color = self._color(color)
        _check_xy(x1, y1)
        _check_xy(x2, y2)
        dev = self._dev()
        # Clip first: Bresenham must never iterate over millions of off-screen
        # pixels just to discard them one at a time in _point().
        clipped = _clip_line(x1, y1, x2, y2, dev.width, dev.height)
        if clipped is None:
            return
        x1, y1, x2, y2 = clipped
        if y1 == y2:
            if x2 < x1:
                x1, x2 = x2, x1
            self._hline(dev, x1, y1, x2 - x1 + 1, color)
            return
        if x1 == x2:
            if y2 < y1:
                y1, y2 = y2, y1
            self._vline(dev, x1, y1, y2 - y1 + 1, color)
            return
        # Bresenham, now bounded by the visible panel (at most ~560 steps).
        dx = x2 - x1
        dy = y2 - y1
        sx = 1 if dx > 0 else -1
        sy = 1 if dy > 0 else -1
        dx = dx if dx > 0 else -dx
        dy = dy if dy > 0 else -dy
        err = dx - dy
        x = x1
        y = y1
        while True:
            self._point(dev, x, y, color)
            if x == x2 and y == y2:
                break
            e2 = err + err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def rect(self, x, y, width, height, color, fill=False):
        color = self._color(color)
        _check_xy(x, y)
        _check_int("width", width)
        _check_int("height", height)
        if width <= 0 or height <= 0:
            return
        dev = self._dev()
        if fill:
            self._fill(dev, x, y, x + width - 1, y + height - 1, color)
        else:
            self._hline(dev, x, y, width, color)
            self._hline(dev, x, y + height - 1, width, color)
            self._vline(dev, x, y, height, color)
            self._vline(dev, x + width - 1, y, height, color)

    def circle(self, x, y, radius, color, fill=False):
        """Draw a circle using a scanline walk over visible rows only.

        A midpoint walk around the whole circumference takes O(radius) steps,
        which is wasteful (or unusable) for huge radii and circles whose arc
        never enters the viewport.  This walk is bounded by the panel height.
        """
        color = self._color(color)
        _check_xy(x, y)
        _check_int("radius", radius)
        if radius <= 0:
            self._point(self._dev(), x, y, color)
            return
        dev = self._dev()
        xf = float(x)
        yf = float(y)
        rf = float(radius)
        r2 = rf * rf
        # Bounding-box rejection: the whole circle is off one side.
        if (xf + rf < 0 or xf - rf >= dev.width or
                yf + rf < 0 or yf - rf >= dev.height):
            return
        # Rejection when the viewport lies entirely inside the circle (the
        # farthest screen corner is still inside it, so no arc is visible).
        corner_x = 0.0 if 2 * xf >= dev.width - 1 else float(dev.width - 1)
        corner_y = 0.0 if 2 * yf >= dev.height - 1 else float(dev.height - 1)
        ddx = xf - corner_x
        ddy = yf - corner_y
        if r2 > ddx * ddx + ddy * ddy:
            return
        row0 = int(yf - rf)
        row1 = int(yf + rf)
        if row0 < 0:
            row0 = 0
        if row1 >= dev.height:
            row1 = dev.height - 1
        max_x = float(dev.width - 1)
        for row in range(row0, row1 + 1):
            dyf = float(row - y)
            inside = r2 - dyf * dyf
            if inside < 0:
                continue
            half = sqrt(inside)
            left = xf - half
            right = xf + half
            if fill:
                if right < 0 or left >= dev.width:
                    continue
                if left < 0:
                    left = 0.0
                if right > max_x:
                    right = max_x
                il = int(left)
                ir = int(right)
                self._hline(dev, il, row, ir - il + 1, color)
            else:
                if 0 <= left < dev.width:
                    self._point(dev, int(left), row, color)
                if 0 <= right < dev.width:
                    self._point(dev, int(right), row, color)

    def text(self, x, y, text, color, size=1):
        """Draw text with the built-in 8x8 font, scaled by integer size (1-8)."""
        color = self._color(color)
        _check_xy(x, y)
        if not isinstance(size, int) or size < 1 or size > 8:
            raise ValueError("size must be an integer in 1..8")
        dev = self._dev()
        hi = color >> 8
        lo = color & 0xFF
        bg = 0xFFFF if self._host.flip_colors else 0x0000
        bghi = bg >> 8
        bglo = bg & 0xFF
        glyph = self._glyph
        rowbuf = self._text_row
        mv = self._text_mv
        cw = 8 * size
        for i in range(len(text)):
            glyph.fill(0)
            try:
                glyph.text(text[i], 0, 0, 1)
            except ValueError:
                continue  # character not in the built-in 8x8 font
            ox = x + i * cw
            for gy in range(8):
                bi = 0
                for gx in range(8):
                    bit = glyph.pixel(gx, gy)
                    for _ in range(size):
                        if bit:
                            rowbuf[bi] = hi
                            rowbuf[bi + 1] = lo
                        else:
                            rowbuf[bi] = bghi
                            rowbuf[bi + 1] = bglo
                        bi += 2
                for sy in range(size):
                    py = y + gy * size + sy
                    if py < 0 or py >= dev.height:
                        continue
                    sx0 = ox
                    sx1 = ox + cw - 1
                    if sx1 < 0 or sx0 >= dev.width:
                        continue
                    skip = 0
                    if sx0 < 0:
                        skip = -sx0
                        sx0 = 0
                    if sx1 >= dev.width:
                        sx1 = dev.width - 1
                    n = sx1 - sx0 + 1
                    off = skip * 2
                    dev.block(sx0, py, sx1, py, mv[off:off + n * 2])

    def image(self, x, y, image_data):
        """Blit (width, height, rgb565_bytes) with clipping.

        image_data must be a 3-tuple; pixels are row-major RGB565, two bytes
        per pixel, high byte first.  A memoryview is used to avoid copies.
        """
        dev = self._dev()
        _check_xy(x, y)
        if not isinstance(image_data, tuple) or len(image_data) != 3:
            raise ValueError("image_data must be (width, height, bytes)")
        w = image_data[0]
        h = image_data[1]
        data = image_data[2]
        _check_int("image width", w)
        _check_int("image height", h)
        if w <= 0 or h <= 0:
            raise ValueError("image width and height must be positive integers")
        if len(data) < w * h * 2:
            raise ValueError("image_data buffer is too small")
        x0 = x
        y0 = y
        x1 = x + w - 1
        y1 = y + h - 1
        if x1 < 0 or y1 < 0 or x0 >= dev.width or y0 >= dev.height:
            return
        if x0 < 0:
            x0 = 0
        if y0 < 0:
            y0 = 0
        if x1 >= dev.width:
            x1 = dev.width - 1
        if y1 >= dev.height:
            y1 = dev.height - 1
        mv = memoryview(data)
        row_bytes = w * 2
        left = (x0 - x) * 2
        n = (x1 - x0 + 1) * 2
        if self._host.flip_colors:
            scratch = self._scratch
            out = self._fill_mv[:n]
            for dy in range(y0, y1 + 1):
                off = (dy - y) * row_bytes + left
                src = mv[off:off + n]
                for i in range(n):
                    scratch[i] = src[i] ^ 0xFF
                dev.block(x0, dy, x1, dy, out)
        else:
            for dy in range(y0, y1 + 1):
                off = (dy - y) * row_bytes + left
                dev.block(x0, dy, x1, dy, mv[off:off + n])


# ---------------------------------------------------------------------------
# Screen API
# ---------------------------------------------------------------------------

class _Screen:
    def __init__(self, host):
        self._host = host
        self._pin = None
        self._pwm = None
        self._pwm16 = False

    @property
    def width(self):
        self._host._require()
        return self._host._device.width

    @property
    def height(self):
        self._host._require()
        return self._host._device.height

    def clear(self, color):
        color = self._host.draw._color(color)
        host = self._host
        host._require()
        dev = host._device
        host.draw._fill(dev, 0, 0, dev.width - 1, dev.height - 1, color)

    def rotation(self, value):
        _check_rotation(value)
        host = self._host
        host._require()
        host._device.set_rotation(value)
        host._touch_dev.set_rotation(value)

    def brightness(self, value):
        if not isinstance(value, int) or value < 0 or value > 100:
            raise ValueError("brightness must be an integer in 0..100")
        self._host._require()
        if self._pwm is not None:
            if self._pwm16:
                self._pwm.duty_u16(value * 65535 // 100)
            else:
                self._pwm.duty(value * 1023 // 100)
        elif self._pin is not None:
            self._pin.value(1 if value > 0 else 0)

    def invert(self, enabled=True):
        """Toggle display hardware color inversion (INVON/INVOFF)."""
        self._host._require()
        self._host._device.set_invert(enabled)

    def offset(self, x=0, y=0):
        """Set GRAM column/page address offset applied to all drawing.

        Some panels show a 1-pixel edge artifact/line at a border; adjusting
        the offset (often y=1 or y=-1) can move the active window to match
        the physical panel. Offsets are in controller address units.
        """
        self._host._require()
        _check_int("x", x)
        _check_int("y", y)
        self._host._device.set_offset(x, y)

    def flip_colors(self, enabled=True):
        """Enable/disable automatic software color reversal for drawing.

        Enabled by default: all colors passed to draw/screen operations are
        bitwise-inverted (RGB565). Disable to use original color values.
        """
        self._host.flip_colors = bool(enabled)

    def _deinit_backlight(self):
        if self._pwm is not None:
            try:
                self._pwm.deinit()
            except Exception as exc:
                print("cydaio: PWM deinit failed:", exc)
            self._pwm = None
        if self._pin is not None:
            try:
                self._pin.value(0)  # backlight off
            except Exception:
                pass
            self._pin = None

    def _init_backlight(self):
        self._pwm = None
        self._pwm16 = False
        self._pin = None
        self._pin = Pin(_TFT_BL, Pin.OUT, value=1)
        if PWM is None:
            return
        try:
            self._pwm = PWM(self._pin, freq=1000, duty_u16=65535)
            self._pwm16 = True
            return
        except TypeError:
            pass
        except Exception as exc:
            print("cydaio: PWM unavailable, using on/off backlight:", exc)
            return
        try:
            self._pwm = PWM(self._pin, freq=1000)
            self._pwm16 = False
            self._pwm.duty(1023)
        except Exception as exc:
            self._pwm = None
            print("cydaio: PWM unavailable, using on/off backlight:", exc)


# ---------------------------------------------------------------------------
# Touch API
# ---------------------------------------------------------------------------

class _Touch:
    def __init__(self, host):
        self._host = host

    def read(self):
        self._host._require()
        return self._host._touch_dev.read()

    def irq_gating(self, enabled=True):
        """Enable/disable PENIRQ contact gating (enabled by default).

        Disable it only if this panel's PENIRQ line is unreliable; contact is
        then inferred from raw coordinate validity alone.
        """
        self._host._require()
        self._host._touch_dev.irq_enabled = bool(enabled)

    def _wait(self, want_press, timeout_ms):
        drv = self._host._touch_dev
        start = ticks_ms()
        while True:
            if (drv.raw() is not None) == want_press:
                return True
            if ticks_diff(ticks_ms(), start) >= timeout_ms:
                return False
            sleep_ms(20)

    def _average(self):
        drv = self._host._touch_dev
        sx = 0
        sy = 0
        n = 0
        for _ in range(5):
            sample = drv.raw()
            if sample is not None:
                sx += sample[0]
                sy += sample[1]
                n += 1
            sleep_ms(20)
        if n == 0:
            raise RuntimeError("cydaio: touch disappeared during calibration")
        return sx // n, sy // n

    @staticmethod
    def _target(draw, x, y, color):
        draw.line(x - 8, y, x + 8, y, color)
        draw.line(x, y - 8, x, y + 8, color)

    def calibrate(self):
        """Interactive four-point affine calibration in the current rotation.

        Waits for the screen to be released first, then draws four corner
        crosshairs and waits for a fresh press-and-release on each.  Fits a
        full affine transform, so swapped/mirrored axes and skew are corrected.
        Blocks until done (10 s press timeout per target).  Result lives in RAM
        only: it is lost on reset.  The crosshairs are erased afterwards.
        """
        host = self._host
        host._require()
        drv = host._touch_dev
        dev = host._device
        w = dev.width
        h = dev.height
        m = 24
        points = ((m, m), (w - 1 - m, m), (m, h - 1 - m), (w - 1 - m, h - 1 - m))
        targets = []
        for px, py in points:
            nx, ny = drv.to_native(px, py, drv.rotation)
            targets.append(((px, py), (nx, ny)))
        # Never start while a previous press is still held down.
        if not self._wait(False, 5000):
            raise RuntimeError("cydaio: release the screen before calibrating")
        samples = []
        try:
            for target in targets:
                px = target[0][0]
                py = target[0][1]
                self._target(host.draw, px, py, WHITE)
                # Wait for a genuine new press, not a stale one.
                if not self._wait(False, 5000):
                    raise RuntimeError("cydaio: release the screen at the target")
                if not self._wait(True, 10000):
                    # Some units never assert PENIRQ. Fall back to raw-range
                    # contact detection once, then keep it for this session.
                    if drv.irq_enabled:
                        print("cydaio: PENIRQ never asserted; using raw-range touch detection")
                        drv.irq_enabled = False
                        if not self._wait(False, 2000):
                            raise RuntimeError("cydaio: release the screen before calibrating")
                        if not self._wait(True, 10000):
                            raise RuntimeError("cydaio: calibration timed out")
                    else:
                        raise RuntimeError("cydaio: calibration timed out")
                raw = self._average()
                samples.append((raw[0], raw[1], target[1][0], target[1][1]))
                if not self._wait(False, 5000):
                    raise RuntimeError("cydaio: lift your finger after the tap")
                self._target(host.draw, px, py, BLACK)
        finally:
            for target in targets:
                self._target(host.draw, target[0][0], target[0][1], BLACK)
        drv.apply_calibration(samples)
        return True


# ---------------------------------------------------------------------------
# Current state manager
# ---------------------------------------------------------------------------

class _Current:
    """Snapshot of the latest touch state, refreshed by update()."""

    def __init__(self, host):
        self._host = host
        self.touch = None
        self.raw_touch = None
        self.pressed = False
        self.x = None
        self.y = None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class CYDAIO:
    def __init__(self):
        self._initialized = False
        self._device = None
        self._touch_dev = None
        self.flip_colors = True  # reverse/flip drawn colors by default
        self.draw = _Draw(self)
        self.screen = _Screen(self)
        self.touch = _Touch(self)
        self.current = _Current(self)

    def _require(self):
        if not self._initialized:
            raise RuntimeError("cydaio: call cyd.init() before using the API")

    def _cleanup(self):
        """Release every resource acquired so far; always safe to call."""
        try:
            self.screen._deinit_backlight()
        except Exception:
            pass
        if self._touch_dev is not None:
            self._touch_dev.deinit()
            self._touch_dev = None
        if self._device is not None:
            self._device.deinit()
            self._device = None
        state = self.current
        state.touch = None
        state.raw_touch = None
        state.pressed = False
        state.x = None
        state.y = None
        self._initialized = False

    def init(self, flip_colors=True):
        """Configure display, backlight and touch.  Safe to call repeatedly.

        ``flip_colors`` reverses/flips all drawing colors by default; pass
        ``False`` (or call ``cyd.screen.flip_colors(False)``) to get the
        original RGB565 color values.
        """
        self.flip_colors = bool(flip_colors)
        if self._initialized:
            return self
        try:
            self._device = _ILI9341()
            self.screen._init_backlight()
            self._touch_dev = _XPT2046()
        except Exception as exc:
            # Clean up whatever was opened before the failure (SPI buses,
            # PWM/backlight) so a retry does not leak hardware resources.
            self._cleanup()
            raise RuntimeError("cydaio: hardware init failed: %s" % exc)
        self._initialized = True
        return self

    def rgb(self, r, g, b):
        """Same as the module-level cyd.rgb(); available on the instance too."""
        return _rgb(r, g, b)

    def deinit(self):
        """Release display SPI, touch SPI and PWM.  Safe to call repeatedly."""
        self._cleanup()

    def update(self):
        """Poll touch once.  Non-blocking, no display writes."""
        self._require()
        drv = self._touch_dev
        point = drv.read()
        state = self.current
        state.touch = point
        state.raw_touch = drv.last_raw
        if point is None:
            state.pressed = False
            state.x = None
            state.y = None
        else:
            state.pressed = True
            state.x = point[0]
            state.y = point[1]


# Module singleton: the API objects exist at import, but refuse hardware work
# until init() is called.  This keeps cyd.draw/screen/touch/current stable.
_cyd = CYDAIO()

init = _cyd.init
deinit = _cyd.deinit
update = _cyd.update
draw = _cyd.draw
screen = _cyd.screen
touch = _cyd.touch
current = _cyd.current
