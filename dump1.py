"""Component dump for one system, to design thresholds."""
import numpy as np
from PIL import Image
from scipy import ndimage

im = Image.open("hd/9ea7c2b8c0d10597e7df035f88641b67349774742.jpg").convert("RGB")
a = np.asarray(im).astype(int)
R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
red = (R - G > 40) & (R - B > 40) & (R > 90)
dark = (a.sum(2) < 480) & (~red)

def comps(mask, y0, y1, x0=0, x1=None, minpx=6):
    x1 = x1 or mask.shape[1]
    sub = mask[y0:y1, x0:x1]
    lab, n = ndimage.label(sub, structure=np.ones((3, 3)))
    out = []
    sl = ndimage.find_objects(lab)
    for i, s in enumerate(sl, 1):
        ys, xs = s
        px = int((lab[s] == i).sum())
        if px < minpx:
            continue
        out.append(dict(x0=xs.start + x0, x1=xs.stop + x0, y0=ys.start + y0, y1=ys.stop + y0,
                        w=xs.stop - xs.start, h=ys.stop - ys.start, px=px))
    out.sort(key=lambda d: d["x0"])
    return out

# red rows
print("=== RED row profile (page1) ===")
rp = red.sum(1)
inband = rp > 50
runs = []
s = None
for y, v in enumerate(inband):
    if v and s is None:
        s = y
    elif not v and s is not None:
        runs.append((s, y)); s = None
if s is not None: runs.append((s, len(inband)))
print([(r, int(rp[r[0]:r[1]].max())) for r in runs])

ky0, ky1 = runs[0]
ny0, ny1 = ky0 - 115, ky0 - 8
print("=== DARK comps in note band", (ny0, ny1), "===")
for c in comps(dark, ny0, ny1):
    print(f"x{c['x0']:5d}-{c['x1']:5d} y{c['y0']:5d}-{c['y1']:5d} w{c['w']:3d} h{c['h']:3d} px{c['px']:5d}")
print("=== RED comps in key band", (ky0, ky1), "===")
for c in comps(red, ky0, ky1, minpx=4):
    print(f"x{c['x0']:5d}-{c['x1']:5d} y{c['y0']:5d}-{c['y1']:5d} w{c['w']:3d} h{c['h']:3d} px{c['px']:5d}")
