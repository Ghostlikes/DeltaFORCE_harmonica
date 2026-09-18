import json, os

# --- 让本脚本无论放在哪一层子目录，都能 import 到项目根下的模块（play.py / score.py / keymap.py …）---
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d and not _os.path.isfile(_os.path.join(_d, "play.py")):
    _p = _os.path.dirname(_d)
    if _p == _d:
        break
    _d = _p
if _d and _d not in _sys.path:
    _sys.path.insert(0, _d)
from PIL import Image, ImageDraw
os.chdir(r'F:\TUVSUD\harmonica')
sd = json.load(open('song_sys.json', encoding='utf-8'))
IMG = 'hd/9ea7c2b8c0d10597e7df035f88641b67349774742.jpg'
for page, sys, xa, xb, tag in [(0, 2, 0, 380, 'm8'), (0, 1, 0, 540, 'm4')]:
    s = next(x for x in sd if x['page'] == page and x['sys'] == sys)
    print(f"--- {tag}: 页{page+1} 行{sys+1} 该行检测到 {len(s['notes'])} 个字形, bars={s['bars']}")
    got = [n for n in s['notes'] if xa <= n['x'] <= xb]
    print("    该区间检测:", [(round(n['x']), n['digit'], n['sharp'], n['oct'], n['ul'], n['dot']) for n in got])
    im = Image.open(IMG).convert('RGB')
    y0 = min(n['y0'] for n in s['notes']) - 45
    y1 = s['keyrow'] + 50
    S = 3.2
    c = im.crop((xa, y0, xb, y1)).resize((int((xb-xa)*S), int((y1-y0)*S)), Image.LANCZOS)
    d = ImageDraw.Draw(c)
    for n in s['notes']:
        if xa <= n['x'] <= xb:
            x = (n['x']-xa)*S
            d.line([x, 0, x, 16], fill=(0, 110, 255), width=2)
            d.text((x+2, 1), f"{n['digit']}{'#' if n['sharp'] else ''}", fill=(0, 110, 255))
    c.save(f"crops/zoom_{tag}.png")
    print("    ->", f"crops/zoom_{tag}.png", c.size)
