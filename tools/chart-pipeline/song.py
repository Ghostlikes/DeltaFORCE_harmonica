"""jianpu sheet -> notes (digit+accidental+octave+duration) + key annotations + measure validation."""

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
import numpy as np, json, sys
from collections import Counter
from PIL import Image
import extract as ex

DIGIT_SEEDS = [(211,'4'),(344,'3'),(408,'3'),(473,'1'),(535,'1'),(596,'4'),(699,'4'),(764,'1'),
               (823,'1'),(883,'6'),(946,'6'),(1010,'5'),(1073,'6'),(1137,'5'),(1239,'6'),(1312,'5'),
               (1428,'0'),(1497,'0')]
LETTER_SEEDS = [(209,'V'),(342,'C'),(475,'Z'),(538,'Z'),(601,'V'),(703,'V'),(769,'Z'),(825,'Z'),
                (886,'N'),(948,'N'),(1009,'B'),(1076,'N'),(1138,'B'),(1240,'N'),(1316,'B'),
                (466,'('),(490,')'),(529,'('),(553,')'),(592,'('),(619,')'),(694,'('),(720,')'),
                (760,'('),(783,')'),(816,'('),(839,')')]
L2D = {'Z':'1','X':'2','C':'3','V':'4','B':'5','N':'6','M':'7',',':'i'}
D2L = {v:k for k,v in L2D.items()}

def canon(c, mask, size=(18,24), y0m=None, y1m=None):
    y0m = c["y0"] if y0m is None else max(0, y0m)
    y1m = c["y1"] if y1m is None else max(y0m, y1m)
    m = (mask[y0m:y1m+1, c["x0"]:c["x1"]+1]*255).astype('uint8')
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
    _, dark, red = ex.masks("hd/"+ex.PAGES[0])
    s0 = ex.run(0)[0][0]
    ds = []
    for x0, lab in DIGIT_SEEDS:
        m = [c for c in s0["notes"] if c["x0"] == x0 and ex.classify(c) == "digit"]
        if m: ds.append((canon(m[0], dark), lab))
    ls = []
    for x0, lab in LETTER_SEEDS:
        m = [c for c in s0["keys"] if c["x0"] == x0]
        if m: ls.append((canon(m[0], red), lab))
    assert len(ds) == len(DIGIT_SEEDS) and len(ls) == len(LETTER_SEEDS), (len(ds), len(ls))
    return NN(ds), NN(ls)

def runs_in(row, minlen):
    out = []; run = 0; st = 0
    for x, v in enumerate(row):
        if v:
            if run == 0: st = x
            run += 1
        else:
            if run >= minlen: out.append((st, x))
            run = 0
    if run >= minlen: out.append((st, len(row)))
    return out

def analyse_system(dark, red, s, dnn, lnn, page, si, xmin=168):
    ky0, ky1 = s["keyrow"]
    nc = [c for c in s["notes"] if c["x0"] >= xmin and c["y1"] < ky0 - 2]   # 排除小节号/页脚文字
    digs = [c for c in nc if ex.classify(c) == "digit"]
    if not digs: return None
    dy0 = Counter(c["y0"] for c in digs).most_common(1)[0][0]
    ybot = Counter(c["y1"] for c in digs).most_common(1)[0][0]      # modal digit bottom
    notes = []
    for c in digs:
        top_x = max(0, dy0 - c["y0"])             # ink above the digit body (merged 高音点)
        bot_x = max(0, c["y1"] - (dy0 + 23))      # ink below the digit body (merged line / 低音点)
        y0m = c["y1"] - 23 if top_x > 1 else c["y0"]
        if y0m + 23 > c["y1"]: y0m = max(c["y0"], c["y1"] - 23)
        lab, d = dnn(canon(c, dark, y0m=y0m, y1m=y0m + 23))
        n = dict(x=(c["x0"] + c["x1"]) / 2, x0=c["x0"], x1=c["x1"], y0=c["y0"], y1=c["y1"],
                 digit=lab, dist=round(d, 3), sharp=False, oct=0, dot=False, ul=0, merged="")
        if top_x > 1:
            n["oct"] += 1; n["merged"] += "高音点"
        if bot_x >= 2:
            row = dark[c["y1"], c["x0"]:c["x1"] + 1]
            if row.mean() > 0.6:
                n["ul"] += 1; n["merged"] += "减时线"
            else:
                n["oct"] -= 1; n["merged"] += "低音点"
        notes.append(n)
    notes.sort(key=lambda n: n["x"])
    # dots
    for c in nc:
        if ex.classify(c) != "dot": continue
        yc = (c["y0"]+c["y1"])/2; cx = c["x0"]+c["w"]/2
        near = min(notes, key=lambda n: abs(n["x"]-cx))
        if abs(near["x"]-cx) > 26: continue
        if yc < dy0-1:
            if "高音点" in near["merged"]: continue   # 已并入数字字形，避免重复计数
            near["oct"] += 1
        elif yc > near["y1"]+1: near["oct"] -= 1
        else: near["dot"] = True
    # sharps from raw pixels (robust to merges with ties/brackets)
    for n in notes:
        w0, w1 = max(0, n["x0"]-32), max(0, n["x0"]-2)
        n["sharp_px"] = int(dark[dy0-21:dy0+25, w0:w1].sum())
        n["sharp"] = n["sharp_px"] > 115
    # underlines: group horizontal runs into LINES (a 2px-thick line is one line, not two)
    UENV = 13
    seg = []
    for y in range(dy0+20, dy0+20+UENV):
        for a, b in runs_in(dark[y], 15): seg.append((y, a, b))
    for n in notes:
        rows = sorted({y for y, a, b in seg if y > n["y1"] and a-5 <= n["x"] <= b+5})
        lines = 0; prev = None
        for y in rows:
            if prev is None or y - prev >= 2: lines += 1
            prev = y
        n["ul"] = lines
    # ties: arc ink in the band above the digits, between neighbouring notes
    ties = []
    for i in range(len(notes)-1):
        a, b = notes[i], notes[i+1]
        x0, x1 = max(0, int(a["x1"])-4), int(b["x0"])+4
        # 连音线: 只在数字上方窄带里找“长横线”，避免把升号竖线误判为连音线
        best = 0
        for y in range(dy0-17, dy0-10):
            for st, en in runs_in(dark[y, x0:x1], 18):
                best = max(best, en-st)
        cnt = best
        if cnt >= 18:
            same = (a["digit"] == b["digit"] and a["oct"] == b["oct"] and a["sharp"] == b["sharp"])
            ties.append(dict(i=i, j=i+1, px=cnt, tie=bool(same)))
    # barlines from raw pixel columns (robust: barlines often merge with ties/brackets)
    colp = dark[max(0, dy0-18):dy0+41, :].sum(0)
    bcols = [x for x in range(int(xmin), dark.shape[1]) if colp[x] >= 45]
    bars = []
    for x in bcols:
        if bars and x - bars[-1][-1] <= 2: bars[-1].append(x)
        else: bars.append([x])
    bars = [float(np.mean(b)) for b in bars]
    # key glyphs (red): parens vs letters
    kg = []
    for c in s["keys"]:
        if c["x0"] < xmin: continue
        if c["w"] <= 11:                      # 窄字形 = 括号
            lab, d = lnn(canon(c, red))
            kg.append(dict(kind="par", x0=c["x0"], x1=c["x1"], h=c["h"], px=c["px"],
                           label=lab if lab in "()" else "("))
            continue
        lab, d = lnn(canon(c, red))
        if lab in "()":
            kg.append(dict(kind="par", x0=c["x0"], x1=c["x1"], h=c["h"], px=c["px"], label=lab))
        else:
            kg.append(dict(kind="key", x0=c["x0"], x1=c["x1"], h=c["h"], w=c["w"],
                           label=lab, dist=round(d, 3), oct=0))
    kg.sort(key=lambda k: k["x0"])
    for i, k in enumerate(kg):
        if k["kind"] != "key": continue
        p = kg[i-1] if i else None; q = kg[i+1] if i+1 < len(kg) else None
        if p and q and p["kind"] == "par" and q["kind"] == "par" \
           and k["x0"]-p["x1"] <= 4 and q["x0"]-k["x1"] <= 4:
            k["oct"] = 1
    return dict(page=page, sys=si, keyrow=ky0, dy0=dy0, ybot=ybot, notes=notes,
                ties=ties, bars=bars, keys=kg)

def measures(sysd):
    """split notes into measures at barlines; returns list of lists of note idx"""
    bars = sysd["bars"]; idx = list(range(len(sysd["notes"])))
    out = []; cur = []
    for i in idx:
        x = sysd["notes"][i]["x"]
        while bars and bars[0] < x - 2:
            out.append(cur); cur = []; bars.pop(0)
        cur.append(i)
    out.append(cur)
    return [m for m in out if m]

def dur_of(n):
    v = {0: 1.0, 1: 0.5, 2: 0.25}.get(min(n["ul"], 2), 0.25)
    if n["dot"]: v *= 1.5
    return v

if __name__ == "__main__":
    dnn, lnn = build()
    all_sys = []
    for pi in range(3):
        _, dark, red = ex.masks("hd/"+ex.PAGES[pi])
        for si, s in enumerate(ex.run(pi)[0]):
            d = analyse_system(dark, red, s, dnn, lnn, pi, si)
            if d: all_sys.append(d)
    json.dump(all_sys, open("song_sys.json", "w"), ensure_ascii=False)
    print(f"systems parsed: {len(all_sys)}")
    tot = mis = 0; badm = []
    for sd in all_sys:
        ms = measures(sd)
        for k, m in enumerate(ms):
            beat = 0.0; prev = None
            for i in m:
                n = sd["notes"][i]
                d = dur_of(n)
                if prev is not None and any(t["i"] == prev and t["j"] == i and t["tie"] for t in sd["ties"]):
                    d = 0.0
                beat += d; prev = i
            if abs(beat - 4.0) > 0.01:
                badm.append((sd["page"], sd["sys"], k, round(beat, 2),
                             " ".join(f"{'#' if sd['notes'][i]['sharp'] else ''}{sd['notes'][i]['digit']}"
                                      f"{'+' if sd['notes'][i]['oct']>0 else ''}"
                                      f"{'/'*sd['notes'][i]['ul']}{'.' if sd['notes'][i]['dot'] else ''}"
                                      f"@{sd['notes'][i]['x']:.0f}" for i in m)))
    print(f"measures != 4.0 beats: {len(badm)}")
    for b in badm[:40]: print("   ", b)
    # digit<->letter cross-check
    ok = n_ = 0; bad = []
    for sd in all_sys:
        for n in sd["notes"]:
            ks = [k for k in sd["keys"] if k["kind"] == "key" and abs((k["x0"]+k["x1"])/2 - n["x"]) < 20]
            if not ks: continue
            k = min(ks, key=lambda k: abs((k["x0"]+k["x1"])/2-n["x"])); n_ += 1
            if D2L.get(n["digit"]) == k["label"]: ok += 1
            else: bad.append((sd["page"], sd["sys"], round(n["x"]), n["digit"], k["label"], n["dist"], k["dist"]))
    print(f"digit<->letter agree {ok}/{n_}")
    for b in bad[:30]: print("    MISMATCH", b)
