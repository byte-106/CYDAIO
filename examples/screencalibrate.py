import cydaio as cyd

# Calibrate touch, then paint pixels where you press.
# Tip: if calibration times out, try: cyd.touch.irq_gating(False)

cyd.init()
cyd.touch.calibrate()
cyd.screen.clear(cyd.BLACK)

last = None
while True:
    cyd.update()
    if cyd.current.pressed:
        point = (cyd.current.x, cyd.current.y)
        if point != last:  # draw only when the touch moves
            cyd.draw.pixel(point[0], point[1], cyd.WHITE)
            last = point
    else:
        last = None
