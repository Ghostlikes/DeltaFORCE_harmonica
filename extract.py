"""Extract note components + key-letter components from the harmonica jianpu sheets."""
import numpy as np, json, os, sys
from PIL import Image
from scipy import ndimage

HD = "hd"
PAGES = ["9ea7c2b8c0d10597e7df035f88641b67349774742.jpg",
         "717ce7eb95fa4b80dd75466af169580a349774742.jpg",
         "ee698e2c4482ac3f4dfe9948967a8304349774742.jpg"]

def masks(path):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(int)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    red = (R - G > 40) & (R - B > 40) & (R > 90)
    dark = (a.sum(2) < 520) & (~red)
    return a, dark, red

def find_bands(mask, minpx=40, gap=4):
    prof = mask.sum(1)
    rows = prof > minpx
    runs, s = [], None
    for y, v in enumerate(rows):
        if v and s is None:
            s = y
        elif not v and s is not None:
            runs.append((s, y)); s = None
    if s is not None: runs.append((s, len(rows)))
    # merge runs separated by < gap
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(list(r))
    return [tuple(r) for r in merged if r[1] - r[0] > 5]

def comps(mask, y0, y1, x0=0, x1=None, minpx=8):
    x1 = x1 if x1 else mask.shape[1]
    lab, n = ndimage.label(mask[y0:y1, x0:x1], structure=np.ones((3, 3)))
    out = []
    for i, s in enumerate(ndimage.find_objects(lab), 1):
        ys, xs = s
        px = int((lab[s] == i).sum())
        if px < minpx: continue
        out.append(dict(x0=int(xs.start + x0), x1=int(xs.stop + x0),
                        y0=int(ys.start + y0), y1=int(ys.stop + y0),
                        w=int(xs.stop - xs.start), h=int(ys.stop - ys.start), px=px))
    out.sort(key=lambda d: (d["x0"], d["y0"]))
    return out

def classify(c):
    w, h, px = c["w"], c["h"], c["px"]
    if h <= 4 and w >= 12: return "underline"
    if w <= 6 and h >= 35: return "barline"
    if h >= 33 and 7 <= w <= 24: return "sharp"
    if 16 <= h <= 32 and 4 <= w <= 26: return "digit"
    if h <= 13 and w <= 13: return "dot"
    return "other"

def run(page_idx):
    path = os.path.join(HD, PAGES[page_idx])
    a, dark, red = masks(path)
    kbands = find_bands(red, minpx=40)
    systems = []
    for (ky0, ky1) in kbands:
        ny0, ny1 = ky0 - 90, ky1 + 5 - 60   # note band: digits ~471-511 for keyrow 534
        ny0 = ky0 - 78; ny1 = ky0 + 60      # cover digits + pen-dots above and underlines below
        nc = comps(dark, ny0, ny1)
        kc = comps(red, ky0 - 6, ky1 + 6, minpx=4)
        systems.append(dict(keyrow=(ky0, ky1), noteband=(ny0, ny1),
                            notes=nc, keys=kc))
    return systems, (a, dark, red)

if __name__ == "__main__":
    pi = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    systems, _ = run(pi)
    for si, s in enumerate(systems):
        print(f"--- system {si} keyrow={s['keyrow']} ---")
        for kind, lst in (("NOTE", s["notes"]), ("KEY", s["keys"])):
            for c in lst:
                print(f"  {kind:4s} {classify(c):9s} x{c['x0']:5d}-{c['x1']:5d} y{c['y0']:4d}-{c['y1']:4d} w{c['w']:3d} h{c['h']:3d} px{c['px']:5d}")
        if si >= 1: break
