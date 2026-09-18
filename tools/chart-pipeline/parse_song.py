"""Full pipeline: jianpu sheet (3 pages) -> structured note stream + key/ops stream.

Glyph classes are learned from labelled seeds (page 0, system 0) that were read from
a VLM montage and independently cross-checked against the key-letter row:
  digit 4->V, 1->Z, 6->N, 5->B, 3->C  (user mapping ZXCVBNM, = 1..7,i)
"""

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
import numpy as np, json, os, sys
from PIL import Image
from scipy import ndimage

import extract as ex

DIGIT_SEEDS = [  # (page, x0, label)
    (211,'4'),(344,'3'),(408,'3'),(473,'1'),(535,'1'),(596,'4'),
    (699,'4'),(764,'1'),(823,'1'),(883,'6'),(946,'6'),(1010,'5'),
    (1073,'6'),(1137,'5'),(1239,'6'),(1312,'5'),(1428,'0'),(1497,'0'),
]
LETTER_SEEDS = [  # (page, x0, label)
    (209,'V'),(342,'C'),(475,'Z'),(538,'Z'),(601,'V'),(703,'V'),(769,'Z'),(825,'Z'),
    (886,'N'),(948,'N'),(1009,'B'),(1076,'N'),(1138,'B'),(1240,'N'),(1316,'B'),
    (466,'('),(490,')'),(529,'('),(553,')'),(592,'('),(619,')'),(694,'('),(720,')'),
    (760,'('),(783,')'),(816,'('),(839,')'),
]

def canon(c, dark, size=(18,24)):
    m = (dark[c["y0"]:c["y1"]+1, c["x0"]:c["x1"]+1]*255).astype('uint8')
    im = Image.fromarray(m).resize(size, Image.BILINEAR)
    return (np.asarray(im) > 110).astype(np.uint8)

class NN:
    def __init__(self, seeds):     # seeds: list of (canon_bitmap, label)
        self.s = seeds
    def __call__(self, bm):
        best, bl = 1e9, None
        for sb, lb in self.s:
            d = np.mean(np.abs(bm.astype(int)-sb.astype(int)))
            if d < best: best, bl = d, lb
        return bl, best

def build_classifiers():
    a, dark, red = ex.masks("hd/"+ex.PAGES[0])
    systems, _ = ex.run(0)
    s0 = systems[0]
    ds = []
    for x0, lab in DIGIT_SEEDS:
        for c in s0["notes"]:
            if c["x0"] == x0:
                ds.append((canon(c, dark), lab)); break
    ls = []
    for x0, lab in LETTER_SEEDS:
        for c in s0["keys"]:
            if c["x0"] == x0:
                ls.append((canon(c, dark), lab)); break
    print(f"# digit seeds {len(ds)}  letter seeds {len(ls)}")
    return NN(ds), NN(ls)

def analyze_page(pi, dnn, lnn, verbose=False):
    path = "hd/"+ex.PAGES[pi]
    a, dark, red = ex.masks(path)
    systems, pagesize = ex.run(pi)
    # per-page vertical calibration from the digit class
    digs_all = [c for s in systems for c in s["notes"] if ex.classify(c) == "digit"]
    dy0 = int(np.median([c["y0"] for c in digs_all]))
    dy1 = int(np.median([c["y1"] for c in digs_all]))
    keys_all = [c for s in systems for c in s["keys"] if c["h"] <= 21 and c["h"] >= 14]
    ky_off = int(np.median([c["y0"] for c in keys_all]))
    lines = [c for s in systems for c in s["notes"] if c["h"] <= 4 and c["w"] >= 12]
    uy = int(np.median([c["y0"] for c in lines])) if lines else None
    if verbose:
        print(f"page{pi}: digit band y{dy0}-{dy1}  letter y0~{ky_off}  underline y~{uy}  "
              f"(n={len(digs_all)},{len(keys_all)},{len(lines)})")
    out = []
    for si, s in enumerate(systems):
        ky0 = s["keyrow"][0]
        notes = []
        for c in s["notes"]:
            k = ex.classify(c)
            if k == "digit":
                lab, d = dnn(canon(c, dark))
                notes.append(dict(kind="note", x=(c["x0"]+c["x1"])/2, x0=c["x0"], y0=c["y0"], y1=c["y1"],
                                  digit=lab, dist=round(float(d),3),
                                  oct=0, sharp=False, dot=False, ul=0))
            elif k == "sharp":
                notes.append(dict(kind="acc", x=(c["x0"]+c["x1"])/2, x0=c["x0"], y0=c["y0"], y1=c["y1"]))
            elif k == "dot":
                notes.append(dict(kind="dot", x=(c["x0"]+c["x1"])/2, x0=c["x0"], y0=c["y0"], y1=c["y1"],
                                  yc=(c["y0"]+c["y1"])/2, w=c["w"]))
            elif k == "underline":
                notes.append(dict(kind="ul", x0=c["x0"], x1=c["x1"], y0=c["y0"], w=c["w"]))
            elif k == "barline":
                notes.append(dict(kind="bar", x=(c["x0"]+c["x1"])/2, x0=c["x0"], y0=c["y0"], y1=c["y1"]))
            else:
                notes.append(dict(kind="other", x0=c["x0"], x1=c["x1"], y0=c["y0"], y1=c["y1"],
                                  w=c["w"], h=c["h"]))
        keys = []
        for c in s["keys"]:
            if c["h"] > 21 or c["w"] > 22:
                keys.append(dict(kind="?", x0=c["x0"], y0=c["y0"], h=c["h"], w=c["w"]))
            else:
                lab, d = lnn(canon(c, dark))
                keys.append(dict(kind="key", x0=c["x0"], x1=c["x1"], y0=c["y0"], label=lab, dist=round(float(d),3),
                                 h=c["h"], w=c["w"]))
        out.append(dict(page=pi, system=si, keyrow=ky0, items=notes, keys=keys))
    return out, dict(dy0=dy0, dy1=dy1, ky_off=ky_off, uy=uy)

if __name__ == "__main__":
    dnn, lnn = build_classifiers()
    for pi in range(3):
        _, cal = analyze_page(pi, dnn, lnn, verbose=True)
