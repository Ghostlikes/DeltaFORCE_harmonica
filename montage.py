"""Build labeled montages of glyphs so a VLM can read them one grid at a time."""
import numpy as np, os, sys
from PIL import Image, ImageDraw

HD = "hd"
PAGES = ["9ea7c2b8c0d10597e7df035f88641b67349774742.jpg",
         "717ce7eb95fa4b80dd75466af169580a349774742.jpg",
         "ee698e2c4482ac3f4dfe9948967a8304349774742.jpg"]

def montage(page, glyphs, out, cols=8, H=150, gap=26, margin=6):
    """glyphs: list of dicts with x0,x1,y0,y1 and a 'tag'."""
    im = Image.open(os.path.join(HD, PAGES[page])).convert("RGB")
    tiles = []
    for g in glyphs:
        c = im.crop((g["x0"] - margin, g["y0"] - margin, g["x1"] + margin, g["y1"] + margin))
        s = H / c.height
        c = c.resize((max(1, int(c.width * s)), H), Image.LANCZOS)
        tiles.append(c)
    W = cols * (H + gap) + gap
    rows = (len(tiles) + cols - 1) // cols
    out_im = Image.new("RGB", (W, rows * (H + gap) + gap), (255, 255, 255))
    d = ImageDraw.Draw(out_im)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        x = gap + c * (H + gap) + (H - t.width) // 2
        y = gap + r * (H + gap)
        out_im.paste(t, (x, y))
        d.rectangle([gap + c * (H + gap) - 6, y - 6, gap + c * (H + gap) + H + 6, y + H + 6], outline=(200, 200, 200))
        d.text((gap + c * (H + gap), y + H + 8), str(i + 1), fill=(120, 120, 120))
    out_im.save(out)
    print("saved", out, out_im.size, "glyphs:", len(glyphs))
    for i, g in enumerate(glyphs):
        print(f"  #{i+1:2d} x{g['x0']}-{g['x1']} y{g['y0']}-{g['y1']} {g.get('tag','')}")
