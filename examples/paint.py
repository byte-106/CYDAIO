import cydaio as cyd

# Simple finger paint: touch the screen to draw.
# Pixels stay until you clear/reset the board.
# Colors are flipped by default on CYD panels; pass flip_colors=False for original RGB565.

cyd.init()
cyd.screen.clear(cyd.BLACK)
cyd.draw.text(8, 8, "Paint! Touch to draw", cyd.WHITE, size=1)
cyd.draw.text(8, 20, "Reset board to clear", cyd.WHITE, size=1)

last = None
while True:
    cyd.update()
    if cyd.current.pressed:
        x = cyd.current.x
        y = cyd.current.y
        if (x, y) != last:
            # Draw a small 2x2 block so it's easy to see.
            cyd.draw.rect(x, y, 2, 2, cyd.BLUE, fill=True)
            last = (x, y)
    else:
        last = None
