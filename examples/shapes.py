import cydaio as cyd

# Real shapes demo: each shape is drawn with a label next to it.

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(8, 6, "CYDAIO shapes", cyd.WHITE, size=2)

# .:pixel
cyd.draw.pixel(20, 45, cyd.WHITE)
cyd.draw.pixel(21, 45, cyd.WHITE)
cyd.draw.pixel(20, 46, cyd.WHITE)
cyd.draw.pixel(21, 46, cyd.WHITE)
cyd.draw.text(40, 42, ".:pixel", cyd.WHITE)

# /:line
cyd.draw.line(10, 80, 50, 60, cyd.RED)
cyd.draw.text(60, 66, "/:line", cyd.RED)

# []:rect
cyd.draw.rect(10, 95, 40, 25, cyd.GREEN)
cyd.draw.text(60, 102, "[]:rect", cyd.GREEN)

# [#]:fill
cyd.draw.rect(10, 130, 40, 25, cyd.BLUE, fill=True)
cyd.draw.text(60, 137, "[#]:fill", cyd.BLUE)

# o:circle
cyd.draw.circle(30, 180, 16, cyd.YELLOW)
cyd.draw.text(60, 174, "o:circle", cyd.YELLOW)

# @:fill circle
cyd.draw.circle(30, 225, 16, cyd.CYAN, fill=True)
cyd.draw.text(60, 219, "@:circle", cyd.CYAN)

# txt:text
cyd.draw.text(10, 255, "Hi!", cyd.MAGENTA, size=2)
cyd.draw.text(60, 260, "txt:text", cyd.MAGENTA)

# img:image (a tiny 8x8 checkerboard)
w = h = 8
pixels = bytearray()
for y in range(h):
    for x in range(w):
        color = cyd.ORANGE if (x + y) % 2 == 0 else cyd.BLACK
        pixels.append(color >> 8)
        pixels.append(color & 0xFF)
cyd.draw.image(10, 290, (w, h, pixels))
cyd.draw.text(60, 290, "img:image", cyd.ORANGE)
