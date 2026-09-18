"""reparse.py — 按【正确的简谱语法】从原始图像重建演奏事件表（v3）。

旧管线致命缺陷：
  1) 完全不处理「增时线」`-`（延长一拍）→ 小节凑不满 4 拍 → play.py 拿静音补齐
     → 听感正是 "ABC 缓一会 DE 缓一会 FG"。
  2) 数字与下划线/升号粘连时整块连通域被丢弃 → 漏音（页1行3 第1小节首音 #4 整颗丢失）。

本版要点：
  * 红色按键字母行与数字行在小节内一一对应，但**逐行可能有整格 x 偏移**，
    所以两行按【排序后顺序配对】，不按 x 邻近配对；
  * 音级由字形模板（旧管线已验证的 digit 标签）最近邻分类，'0' 视为休止；
  * 时值 = 减时线层数(1/0.5/0.25) × 附点1.5 + 增时线每条 +1 拍；
  * 校验：每小节必须正好 4 拍（全曲 123 小节）。
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
import json, os, sys
from collections import defaultdict, Counter
import numpy as np
from PIL import Image
from scipy import ndimage

os.chdir(r'F:\TUVSUD\harmonica')
PAGES = {
    0: 'hd/9ea7c2b8c0d10597e7df035f88641b67349774742.jpg',
    1: 'hd/717ce7eb95fa4b80dd75466af169580a349774742.jpg',
    2: 'hd/ee698e2c4482ac3f4dfe9948967a8304349774742.jpg',
}
BPM, BPB = 125, 4
UL_VAL = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}
DASH, DOT_MUL = 1.0, 1.5
LETTER = {'1': 'Z', '2': 'X', '3': 'C', '4': 'V', '5': 'B', '6': 'N', '7': 'M', 'i': ','}
TSZ = 16


def col_runs(mask, y0, y1, x0, x1, gap=0, minw=1):
    p = mask[y0:y1, x0:x1].sum(0)
    runs, st, last = [], None, -10 ** 9
    for i, v in enumerate(p):
        if v > 0:
            if st is None:
                st = i
            last = i
        elif st is not None and i - last > gap:
            if last - st + 1 >= minw:
                runs.append((st + x0, last + x0))
            st = None
    if st is not None and last - st + 1 >= minw:
        runs.append((st + x0, last + x0))
    return runs


def load_page(path):
    im = Image.open(path)
    arr = np.asarray(im.convert('RGB')).astype(int)
    L = np.asarray(im.convert('L')).astype(int)
    R, G, B = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    red = (R - G > 40) & (R - B > 40) & (R > 90)
    return (L < 150) & (~red), red


def norm(crop):
    im = Image.fromarray((crop * 255).astype(np.uint8)).resize((TSZ, TSZ), Image.BILINEAR)
    return (np.asarray(im) > 110)


def extract_line(dark, red, geo):
    kr = geo['keyrow']
    H, W = dark.shape
    runs = col_runs(red, kr - 8, kr + 20, 30, W - 30, gap=8, minw=6)
    letters = []
    for (a, b) in runs:
        labs, octs = Counter(), Counter()
        for k in geo.get('keys', []):
            if a - 3 <= (k['x0'] + k['x1']) / 2 <= b + 3:
                if k.get('label'):
                    labs[k['label']] += 1
                if k.get('oct'):
                    octs[k['oct']] += 1
        letters.append(dict(x0=a, x1=b, cx=(a + b) / 2, label=(labs.most_common(1)[0][0] if labs else None),
                            oct=(octs.most_common(1)[0][0] if octs else 0)))
    win0, win1 = max(0, kr - 74), kr - 16
    rowink = dark[win0:win1, 40:W - 40].sum(1)
    rows = [i for i, v in enumerate(rowink) if v >= 4]
    if not rows:
        return None
    top, bot = win0 + rows[0], win0 + rows[-1]
    y_a, y_b = max(0, top - 30), min(H, bot + 18)
    lab, _ = ndimage.label(dark[y_a:y_b, :], structure=np.ones((3, 3), int))
    G = []
    for sl in ndimage.find_objects(lab):
        ys, xs = sl
        y0, y1, x0, x1 = ys.start + y_a, ys.stop - 1 + y_a, xs.start, xs.stop - 1
        G.append(dict(x0=x0, x1=x1, y0=y0, y1=y1, h=y1 - y0 + 1, w=x1 - x0 + 1,
                      cx=(x0 + x1) / 2, cy=(y0 + y1) / 2, kind='?'))
    # 数字字形候选：高度 >= 20（花括号碎片 h=14~17 被排除）
    dg = [g for g in G if 20 <= g['h'] <= 30 and 5 <= g['w'] <= 40]
    base = int(np.median([g['y1'] for g in dg])) if dg else bot
    dtop = int(np.median([g['y0'] for g in dg])) if dg else top
    for g in G:
        h, w = g['h'], g['w']
        if w > 120 or h > 62:
            g['kind'] = 'big'
        elif h <= 7 and w >= 13:
            # 数字上方 = 连音线弧；数字中部 = 增时线；数字下方 = 减时线
            if g['y1'] < dtop - 1:
                g['kind'] = 'arc'
            elif g['y0'] > dtop + 2 and g['y1'] < base - 2:
                g['kind'] = 'dash'
            else:
                g['kind'] = 'uline'
        elif h >= 29 and w <= 24:
            g['kind'] = 'sharp'
        elif h <= 11 and w <= 11:
            g['kind'] = 'dot'
        elif w >= 20 and h <= 22 and g['y1'] < dtop + 2:
            g['kind'] = 'arc'          # 数字上方的连音线弧（可能带弧度，h 到十几像素）
        elif 20 <= h <= 30 and 5 <= w <= 40:
            g['kind'] = 'digit'
        else:
            g['kind'] = 'other'
    # 小节线：列扫描（跨 dtop-6..base+26 的细高竖线，对与下划线粘连免疫）
    band_cnt = dark[max(0, dtop - 6):base + 27, :].sum(0)
    bars = []
    prev_x = -9
    for x in range(40, W - 40):
        if band_cnt[x] >= 40:
            if x - prev_x > 3:
                bars.append(float(x))
            prev_x = x
    xmin = (min(l['x0'] for l in letters) - 45) if letters else 40
    # 增时线补测：数字中部高度上的"孤立"长横线（与数字粘连时连通域会漏，这里按像素行找）
    extra_dash = []
    for y in range(dtop + 4, base - 3):
        row = dark[y, :]
        x = 0
        while x < W:
            if not row[x]:
                x += 1
                continue
            x2 = x
            while x2 + 1 < W and row[x2 + 1]:
                x2 += 1
            ln = x2 - x + 1
            if 12 <= ln <= 40:
                # 该段各列在这条线上下（±4px）之外必须没有墨迹 => 孤立横线
                col_ink = dark[max(0, y - 5):y - 2, x:x2 + 1].sum() + dark[y + 3:y + 6, x:x2 + 1].sum()
                if col_ink <= 2 and x >= xmin:
                    extra_dash.append(dict(x0=x, x1=x2, y0=y, y1=y, cx=(x + x2) / 2, cy=y,
                                           h=1, w=ln, kind='dash'))
            x = x2 + 1
    # 连音线补测：数字上方(或贴着数字上沿)的宽横线，弧线与数字粘连时连通域会漏
    arc_rows = []
    for y in range(max(0, dtop - 30), dtop + 3):
        row = dark[y, :]
        x = 0
        while x < W:
            if not row[x]:
                x += 1
                continue
            x2 = x
            while x2 + 1 < W and row[x2 + 1]:
                x2 += 1
            if x2 - x + 1 >= 25:
                arc_rows.append((x, x2, y))
            x = x2 + 1
    arcs_auto = []
    for (x0, x1, y) in arc_rows:
        for a in arcs_auto:
            if abs(a['y1'] - y) <= 3 and not (x1 < a['x0'] - 12 or x0 > a['x1'] + 12):
                a['x0'], a['x1'] = min(a['x0'], x0), max(a['x1'], x1)
                a['y0'], a['y1'] = min(a['y0'], y), max(a['y1'], y)
                break
        else:
            arcs_auto.append(dict(x0=x0, x1=x1, y0=y, y1=y, cx=(x0 + x1) / 2, cy=y,
                                  w=x1 - x0 + 1, h=1, kind='arc'))
    arcs = [g for g in G if g['kind'] == 'arc'] + arcs_auto
    dashes = [g for g in G if g['kind'] == 'dash']
    for d in extra_dash:
        if not any(abs(d['cx'] - o['cx']) <= 6 for o in dashes):
            dashes.append(d)
    return dict(kr=kr, top=top, bot=bot, base=base, dtop=dtop, xmin=xmin, letters=letters, G=G,
                bars=bars,
                digits=[g for g in G if g['kind'] == 'digit' and g['x0'] >= xmin],
                sharps=[g for g in G if g['kind'] == 'sharp'],
                dots=[g for g in G if g['kind'] == 'dot'],
                dashes=dashes,
                arcs=arcs)


def ulayers(dark, g, base):
    seg, prev = 0, -9
    for y in range(base + 1, min(dark.shape[0], base + 18)):
        if dark[y, g['x0']:g['x1'] + 1].sum() / max(1, g['w']) >= 0.5:
            if y - prev > 1:
                seg += 1
            prev = y
    return seg


def main():
    raw = json.load(open('song_raw.json', encoding='utf-8'))
    pages = {p: load_page(pth) for p, pth in PAGES.items()}
    ex = []
    for geo in raw:
        dark, red = pages[geo['page']]
        e = extract_line(dark, red, geo)
        if e:
            e.update(page=geo['page'], sys=geo['sys'], dark=dark, raw=geo)
            ex.append(e)
    print(f"提取 {len(ex)} 行 / {len(raw)}")
    # ---- 模板库（旧管线 digit 标签，数字↔字母已验证 100%）----
    bank = defaultdict(list)
    for e in ex:
        for g in e['digits']:
            olds = e['raw']['notes']
            if not olds:
                continue
            c, o = min(((abs((n['x0'] + n['x1']) / 2 - g['cx']), n) for n in olds), key=lambda z: z[0])
            if c <= 10:
                bank[o['digit']].append(norm(e['dark'][g['y0']:g['y1'] + 1, g['x0']:g['x1'] + 1]))
    print("模板库:", {k: len(v) for k, v in sorted(bank.items())})
    # ---- 分类（最近邻），并与旧标签比对 ----
    agree, disagree = 0, 0
    for e in ex:
        for g in e['digits']:
            q = norm(e['dark'][g['y0']:g['y1'] + 1, g['x0']:g['x1'] + 1])
            best, bd = None, 1e9
            for d, arrs in bank.items():
                for a in arrs:
                    dd = int((q ^ a).sum())
                    if dd < bd:
                        bd, best = dd, d
            g['nn'], g['nnd'] = best, bd
            olds = e['raw']['notes']
            if olds:
                c, o = min(((abs((n['x0'] + n['x1']) / 2 - g['cx']), n) for n in olds), key=lambda z: z[0])
                if c <= 10:
                    g['oldlab'] = o['digit']
                    if o['digit'] == best:
                        agree += 1
                    else:
                        disagree += 1
    print(f"字形分类 vs 旧标签: 一致 {agree}  不一致 {disagree}")
    # ---- 组装 ----
    lines, warns = [], []
    st = Counter()
    for e in ex:
        dark, base, dtop = e['dark'], e['base'], e['dtop']
        digs = sorted(e['digits'], key=lambda g: g['cx'])
        rests = [g for g in digs if g['nn'] == '0']
        notes_g = [g for g in digs if g['nn'] != '0']
        let = e['letters']
        if len(let) != len(notes_g):
            warns.append(f"页{e['page']+1}行{e['sys']+1}: 字母{len(let)} 非休止字形{len(notes_g)} 休止{len(rests)}")
        # 红字母与数字按 x 邻近配对（部分行只给部分音符标了字母，不能按顺序配）
        used_l = set()
        pairL = {}
        for i, g in enumerate(notes_g):
            cand = sorted((abs(l['cx'] - g['cx']), j) for j, l in enumerate(let)
                          if j not in used_l and abs(l['cx'] - g['cx']) <= 30)
            if cand:
                used_l.add(cand[0][1])
                pairL[i] = let[cand[0][1]]
        notes = []
        for i, g in enumerate(notes_g):
            L = pairL.get(i)
            octk = L['oct'] if L else 0
            # 高八度点：数字正上方的小点（像素判读，独立于字母行）
            octd = sum(1 for d in e['dots'] if abs(d['cx'] - g['cx']) <= 14 and d['y1'] < dtop - 1)
            sharp = any(g['x0'] - 22 <= s['x1'] <= g['x0'] + 3 and s['y1'] > dtop + 4 for s in e['sharps'])
            dotted = any(g['x1'] < d['x0'] <= g['x1'] + 15 and g['y0'] - 5 <= d['cy'] <= g['y1'] + 3
                         for d in e['dots'])
            # 交叉校验：字母行的 label 应等于 LETTER[音级]
            if L and L['label']:
                if L['label'] == LETTER.get(g['nn']):
                    st['pair_ok'] += 1
                else:
                    st['pair_bad'] += 1
                    if st['pair_bad'] <= 12:
                        warns.append(f"  配对存疑 页{e['page']+1}行{e['sys']+1} x={g['cx']:.0f} "
                                     f"数字{g['nn']}->{LETTER.get(g['nn'])} 但红字母={L['label']}")
            if octk and octd and octk != octd:
                st['oct_bad'] += 1
            notes.append(dict(rest=False, digit=g['nn'], src=g.get('oldlab'), key=LETTER.get(g['nn']),
                              oct=max(octk, octd), octkey=octk, octdot=octd, sharp=sharp,
                              dotted=dotted, ul=ulayers(dark, g, base), dashes=0,
                              nnd=g.get('nnd'), fig=g,
                              meas=sum(1 for b in e['bars'] if b < g['cx'] - 2)))
        for g in rests:
            notes.append(dict(rest=True, digit='0', src=g.get('oldlab'), key=None, oct=0, octkey=0,
                              octdot=0, sharp=False, dotted=False, ul=ulayers(dark, g, base),
                              dashes=0, nnd=g.get('nnd'), fig=g,
                              meas=sum(1 for b in e['bars'] if b < g['cx'] - 2)))
        notes.sort(key=lambda t: t['fig']['cx'])
        # 增时线 -> 左侧最近音符
        for d in e['dashes']:
            best = None
            for t in notes:
                if t['fig']['x1'] < d['x0'] and (best is None or t['fig']['x1'] > best['fig']['x1']):
                    best = t
            if best:
                best['dashes'] += 1
        for t in notes:
            v = UL_VAL.get(min(t['ul'], 3), 0.125)
            if t['dotted']:
                v *= DOT_MUL
            t['beats'] = v + DASH * t['dashes']
        # 连音线：弧线字形 或 旧管线 ties（按 x 映射过来），要求两端同音高
        drop = set()
        tie_pairs = []
        for a in e['arcs']:
            ins = [i for i, t in enumerate(notes)
                   if not t['rest'] and a['x0'] - 22 <= t['fig']['cx'] <= a['x1'] + 22]
            if len(ins) == 2:
                tie_pairs.append((ins[0], ins[1]))
        olds = e['raw']['notes']
        for tt in e['raw'].get('ties', []):
            if not tt.get('tie'):
                continue
            try:
                oi, oj = olds[tt['i']], olds[tt['j']]
            except Exception:
                continue
            ci, cj = (oi['x0'] + oi['x1']) / 2, (oj['x0'] + oj['x1']) / 2
            a = min(range(len(notes)), key=lambda k: abs(notes[k]['fig']['cx'] - ci) if not notes[k]['rest'] else 1e9)
            b = min(range(len(notes)), key=lambda k: abs(notes[k]['fig']['cx'] - cj) if not notes[k]['rest'] else 1e9)
            if a != b and not notes[a]['rest'] and not notes[b]['rest']:
                tie_pairs.append((min(a, b), max(a, b)))
        for (i0, i1) in tie_pairs:
            if i1 in drop or notes[i0]['digit'] != notes[i1]['digit'] or notes[i0].get('rest'):
                continue
            if abs(notes[i1]['fig']['cx'] - notes[i0]['fig']['cx']) > 120:
                continue
            # 连音线必须连接【相邻】且【同一小节】的同音高音符
            if i1 != i0 + 1 or notes[i0]['meas'] != notes[i1]['meas']:
                continue
            if notes[i0].get('oct') != notes[i1].get('oct'):
                continue
            notes[i0]['beats'] += notes[i1]['beats']
            notes[i0]['tie'] = True
            drop.add(i1)
        notes = [t for i, t in enumerate(notes) if i not in drop]
        lines.append(dict(page=e['page'], sys=e['sys'], top=e['top'], base=base, bars=e['bars'],
                          notes=notes, nlet=len(let), nfig=len(notes_g), nrest=len(rests),
                          nsharp=len(e['sharps']), ndash=len(e['dashes']), narc=len(e['arcs'])))
        st['notes'] += len(notes_g)
        st['rest'] += len(rests)
        st['dash'] += sum(t['dashes'] for t in notes)
        st['tie'] += len(drop)
    print("统计:", dict(st))
    print("警告:", len(warns))
    for w in warns[:15]:
        print("   ", w)
    # ---- 校验：每小节 4 拍 ----
    meas = defaultdict(float)
    for L in lines:
        for t in L['notes']:
            meas[(L['page'], L['sys'], t['meas'])] += t['beats']
    c = Counter(round(v, 3) for v in meas.values())
    print(f"\n小节数 {len(meas)}  分布: {c.most_common(8)}")
    bad = sorted((k, round(v, 3)) for k, v in meas.items() if abs(v - BPB) > 1e-6)
    print(f"≠4拍 {len(bad)}/{len(meas)}")
    for k, v in bad[:20]:
        print(f"    页{k[0]+1}行{k[1]+1} 第{k[2]+1}小节={v}")
    # 抽样打印
    for L in lines[:3] + lines[13:15]:
        print(f"\n--- 页{L['page']+1}行{L['sys']+1} 字母{L['nlet']} 字形{L['nfig']} 休止{L['nrest']} "
              f"增时线{L['ndash']} 弧{L['narc']} ---")
        mn = defaultdict(list)
        for t in L['notes']:
            mn[t['meas']].append(t)
        for mi in sorted(mn):
            tot = sum(t['beats'] for t in mn[mi])
            s = " ".join(f"{t['key'] or '0'}{'#' if t['sharp'] else ''}{'^'*t['octdot']}"
                         f"{'.' if t['dotted'] else ''}_{t['ul']}{'-'*t['dashes']}/{t['beats']:g}"
                         + ("~" if t.get('tie') else "") for t in mn[mi])
            print(f"   小节{mi+1} [{tot:g}拍] {s}")
    json.dump(lines, open('reparse_debug.json', 'w', encoding='utf-8'), ensure_ascii=False, default=str)
    print("\n写出 reparse_debug.json")
    # ---------- 生成 score2.json ----------
    fill = sys.argv[1] if len(sys.argv) > 1 else 'extend'
    measures, repairs = [], []
    for L in lines:
        mn = defaultdict(list)
        for t in L['notes']:
            mn[t['meas']].append(t)
        for mi in sorted(mn):
            evs = sorted(mn[mi], key=lambda t: t['fig']['cx'])
            tot = sum(t['beats'] for t in evs)
            events, off = [], 0.0
            for t in evs:
                mods = []
                if t['sharp']:
                    mods.append('middle')
                if t['oct'] > 0:
                    mods.append('right')
                elif t['oct'] < 0:
                    mods.append('left')
                events.append(dict(key=(None if t['rest'] else t['key']), mods=mods,
                                   beat=round(off, 4), beats=round(t['beats'], 4),
                                   sustain=bool(t.get('tie')), note=t['digit'],
                                   rest=bool(t['rest'])))
                off += t['beats']
            if abs(tot - BPB) > 1e-6:
                d = BPB - tot
                last = next((e for e in reversed(events) if e['key']), None)
                if last is not None and fill == 'extend' and d > 0:
                    last['beats'] = round(last['beats'] + d, 4)
                    last['extended'] = round(d, 4)
                    repairs.append((L['page'] + 1, L['sys'] + 1, mi + 1, round(tot, 3), round(d, 3)))
            final = round(sum(e['beats'] for e in events), 4)
            measures.append(dict(line=[L['page'] + 1, L['sys'] + 1], events=events,
                                 beats=final, raw_beats=round(tot, 4),
                                 confident=abs(tot - BPB) < 1e-6))
    total = sum(m['beats'] for m in measures)
    score = dict(bpm=BPM, beats_per_measure=BPB, total_beats=round(total, 3),
                 duration_sec=round(total * 60.0 / BPM, 1), measures=measures)
    json.dump(score, open('score2.json', 'w', encoding='utf-8'), ensure_ascii=False)
    nconf = sum(1 for m in measures if m['confident'])
    print(f"score2.json: {len(measures)} 小节 / {sum(1 for m in measures for e in m['events'])} 事件 / "
          f"{total:g} 拍 ≈{score['duration_sec']}s   满4拍 {nconf} 小节")
    print(f"补足(把缺的拍数延长到该小节最后一个音): {len(repairs)} 处")
    for r in repairs[:12]:
        print(f"    页{r[0]}行{r[1]} 第{r[2]}小节 原 {r[3]} 拍 -> 延长 {r[4]} 拍")
    print("写出 score2.json")


if __name__ == '__main__':
    main()
