import json, os
from PIL import Image, ImageDraw
os.chdir(r'F:\TUVSUD\harmonica')
sd = json.load(open('song_sys.json', encoding='utf-8'))
PAGE = {0: 'hd/9ea7c2b8c0d10597e7df035f88641b67349774742.jpg',
        1: 'hd/717ce7eb95fa4b80dd75466af169580a349774742.jpg',
        2: 'hd/ee698e2c4482ac3f4dfe9948967a8304349774742.jpg'}
S = 2.4
for page, sys, tag in [(0, 1, 'line2'), (0, 2, 'line3')]:
    s = next(x for x in sd if x['page'] == page and x['sys'] == sys)
    im = Image.open(PAGE[page]).convert('RGB')
    y0 = min(n['y0'] for n in s['notes']) - 42
    y1 = s['keyrow'] + 48
    for half, (xa, xb) in enumerate([(0, 900), (760, 1654)]):
        c = im.crop((xa, y0, xb, y1)).resize((int((xb-xa)*S), int((y1-y0)*S)), Image.LANCZOS)
        d = ImageDraw.Draw(c)
        for n in s['notes']:
            if xa <= n['x'] <= xb:
                x = (n['x']-xa)*S
                d.line([x, 0, x, 18], fill=(0, 120, 255), width=2)
                d.text((x+2, 2), f"{n['digit']}{'#' if n['sharp'] else ''}{'^' if n['oct']>0 else ''}"
                       f"{'v' if n['oct']<0 else ''}u{n['ul']}{'D' if n['dot'] else ''}",
                       fill=(0, 120, 255))
        for b in s['bars']:
            if xa <= b <= xb:
                x = (b-xa)*S
                d.line([x, 0, x, 26], fill=(255, 0, 0), width=3)
        c.save(f"crops/qa_{tag}_{'L' if half==0 else 'R'}.png")
        print(f"crops/qa_{tag}_{'L' if half==0 else 'R'}.png", c.size)
    print(f"  {tag}: notes={len(s['notes'])} bars={s['bars']} keyrow={s['keyrow']} y={y0}-{y1}")
