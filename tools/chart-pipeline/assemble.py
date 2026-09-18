"""Assemble the jianpu sheet into measures: notes (digit/sharp/octave/duration) + key letters."""

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
from collections import Counter, defaultdict
from PIL import Image
import extract as ex

DIGIT_SEEDS = [(211,'4'),(344,'3'),(408,'3'),(473,'1'),(535,'1'),(596,'4'),(699,'4'),(764,'1'),
               (823,'1'),(883,'6'),(946,'6'),(1010,'5'),(1073,'6'),(1137,'5'),(1239,'6'),(1312,'5'),
               (1428,'0'),(1497,'0')]
LETTER_SEEDS = [(209,'V'),(342,'C'),(475,'Z'),(538,'Z'),(601,'V'),(703,'V'),(769,'Z'),(825,'Z'),
                (886,'N'),(948,'N'),(1009,'B'),(1076,'N'),(1138,'B'),(1240,'N'),(1316,'B'),
                (466,'('),(490,')'),(529,'('),(553,')'),(592,'('),(619,')'),(694,'('),(720,')'),
                (760,'('),(783,')'),(816,'('),(839,')')]

def canon(c, dark, size=(18,24)):
    m = (dark[c["y0"]:c["y1"]+1, c["x0"]:c["x1"]+1]*255).astype('uint8')
    return (np.asarray(Image.fromarray(m).resize(size, Image.BILINEAR)) > 110).astype(np.uint8)

class NN:
    def __init__(s, seeds): s.s = seeds
    def __call__(s, bm):
        best, bl = 1e9, None
        for sb, lb in s.s:
            d = float(np.mean(np.abs(bm.astype(int)-sb.astype(int))))
            if d < best: best, bl = d, lb
        return bl, best

def build():
    a, dark, red = ex.masks("hd/"+ex.PAGES[0])
    s0 = ex.run(0)[0][0]
    ds = [(canon(c, dark), lab) for x0, lab in DIGIT_SEEDS
          for c in s0["notes"] if c["x0"] == x0]
    ls = [(canon(c, red), lab) for x0, lab in LETTER_SEEDS
          for c in s0["keys"] if c["x0"] == x0]
    return NN(ds), NN(ls)

def page_measures(pi, dnn, lnn, xmin=150):
    a, dark, red = ex.masks("hd/"+ex.PAGES[pi])
    systems = ex.run(pi)[0]
    out = []
    for si, s in enumerate(systems):
        ky0, ky1 = s["keyrow"]
        comps_n = [c for c in s["notes"] if c["x0"] >= xmin]
        digs = [c for c in comps_n if ex.classify(c) == "digit"]
        if not digs: continue
        dy0 = Counter(c["y0"] for c in digs).most_common(1)[0][0]
        dy1 = Counter(c["y1"] for c in digs).most_common(1)[0][0]
        notes = []
        for c in digs:
            lab, d = dnn(canon(c, dark))
            notes.append(dict(x=(c["x0"]+c["x1"])/2, x0=c["x0"], x1=c["x1"], digit=lab,
                              dist=round(d,3), h=c["h"], sharp=False, oct=0, dot=False, ul=0))
        notes.sort(key=lambda n: n["x"])
        # dots
        for c in comps_n:
            if ex.classify(c) != "dot": continue
            yc = (c["y0"]+c["y1"])/2
            near = min(notes, key=lambda n: abs(n["x"]-c["x0"]-c["w"]/2))
            if abs(near["x"]-c["x0"]) > 26: continue
            if yc < dy0 - 1:   near["oct"] += 1                       # 高音点
            elif yc > dy1 + 1: near["oct"] -= 1                       # 低音点
            else:              near["dot"] = True                     # 附点
        # sharps (immediately left of digit)
        for c in comps_n:
            if ex.classify(c) != "sharp": continue
            cx = (c["x0"]+c["x1"])/2
            cand = [n for n in notes if 0 < n["x"]-cx < 30]
            if cand: min(cand, key=lambda n: n["x"]-cx)["sharp"] = True
        # underlines: count lines overlapping each note's x-range (extended)
        for c in comps_n:
            if ex.classify(c) != "underline": continue
            for n in notes:
                if c["x0"] - 6 <= n["x"] <= c["x1"] + 6:
                    n["ul"] += 1
        # barlines & ties
        bars = sorted((c["x0"]+c["x1"])/2 for c in comps_n if ex.classify(c)=="barline")
        # arcs: long dark runs in band just above digits
        band = dark[dy0-18:dy0-8, :]
        arcs = []
        for y in range(band.shape[0]):
            row = band[y]; run = 0
            for x in range(len(row)):
                if row[x]: run += 1
                else:
                    if run >= 14: arcs.append((x-run, x))
                    run = 0
            if run >= 14: arcs.append((len(row)-run, len(row)))
        # merge overlapping arc runs
        arcs.sort(); merged = []
        for a0, a1 in arcs:
            if merged and a0 <= merged[-1][1]+2: merged[-1] = (merged[-1][0], max(merged[-1][1], a1))
            else: merged.append((a0, a1))
        ties = []
        for a0, a1 in merged:
            inv = [i for i, n in enumerate(notes) if a0-4 <= n["x"] <= a1+4]
            if len(inv) >= 2: ties.append((inv[0], inv[-1], a0, a1))
        # key letters
        keyg = []
        for c in s["keys"]:
            if c["x0"] < xmin: continue
            if c["h"] > 21 or c["w"] > 22:
                keyg.append(dict(kind="big", x0=c["x0"], x1=c["x1"], y0=c["y0"], w=c["w"], h=c["h"], y1=c["y1"]))
            else:
                lab, d = lnn(canon(c, red))
                keyg.append(dict(kind="key", x0=c["x0"], x1=c["x1"], label=lab, dist=round(d,3)))
        for i, k in enumerate(keyg):
            if k["kind"] != "key": continue
            k["oct"] = 0
            if k["label"] not in "()":
                prev = keyg[i-1] if i else None
                nxt = keyg[i+1] if i+1 < len(keyg) else None
                if prev and nxt and prev.get("label") == "(" and nxt.get("label") == ")" \
                   and k["x0"]-prev["x1"] <= 4 and nxt["x0"]-k["x1"] <= 4:
                    k["oct"] = 1
        out.append(dict(page=pi, sys=si, keyrow=ky0, dy0=dy0, dy1=dy1, notes=notes,
                        bars=bars, ties=ties, keys=keyg))
    return out

if __name__ == "__main__":
    dnn, lnn = build()
    data = []
    for pi in range(3):
        data += page_measures(pi, dnn, lnn)
    json.dump(data, open("song_raw.json","w"), ensure_ascii=False)
    print("systems:", len(data))
    # quick digit<->letter consistency check
    LETTER2DIG = {'Z':'1','X':'2','C':'3','V':'4','B':'5','N':'6','M':'7',',':'i'}
    DIG2LETTER = {v:k for k,v in LETTER2DIG.items()}
    bad = tot = 0
    for s in data:
        for n in s["notes"]:
            ks = [k for k in s["keys"] if k["kind"]=="key" and k["label"] in LETTER2DIG
                  and abs((k["x0"]+k["x1"])/2 - n["x"]) < 22]
            if not ks: continue
            k = min(ks, key=lambda k: abs((k["x0"]+k["x1"])/2-n["x"]))
            tot += 1
            if DIG2LETTER.get(n["digit"]) != k["label"]:
                bad += 1
                if bad <= 12:
                    print(f"  MISMATCH p{s['page']} sys{s['sys']} x{n['x']:.0f} digit={n['digit']} letter={k['label']}")
    print(f"digit<->letter agreement: {tot-bad}/{tot}")
