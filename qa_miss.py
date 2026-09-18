import json, os
from PIL import Image, ImageDraw
os.chdir(r'F:\TUVSUD\harmonica')
raw = json.load(open('song_raw.json', encoding='utf-8'))
s = raw[2]                     # 页1 行3
print("行3: keyrow", s['keyrow'], "dy", s['dy0'], s['dy1'], " bars", s['bars'])
im = Image.open('hd/9ea7c2b8c0d10597e7df035f88641b67349774742.jpg').convert('RGB')
xa, xb = 40, 320
y0, y1 = s['dy0'] - 40, s['keyrow'] + 45
S = 4.0
c = im.crop((xa, y0, xb, y1)).resize((int((xb-xa)*S), int((y1-y0)*S)), Image.LANCZOS)
d = ImageDraw.Draw(c)
for x in range(xa, xb, 20):
    xx = (x-xa)*S
    d.line([xx, 0, xx, 14], fill=(0, 160, 0), width=1)
    d.text((xx+1, 1), str(x), fill=(0, 140, 0))
d.line([0, (s['dy0']-y0)*S, c.size[0], (s['dy0']-y0)*S], fill=(255, 0, 255), width=1)
d.line([0, (s['keyrow']-y0)*S, c.size[0], (s['keyrow']-y0)*S], fill=(255, 0, 255), width=1)
c.save('crops/zoom_miss.png')
print("->", 'crops/zoom_miss.png', c.size)
