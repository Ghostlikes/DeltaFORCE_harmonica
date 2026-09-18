"""gen_score.py — 把解析出的曲谱 (song_sys.json) 编译成可直接播放的事件表 score.json

事件模型(每个音一条):
    {"key":"V","mods":["middle","right"],"beat":<小节内起拍>,"beats":<时值>,"sustain":false}
休止: {"key":null,"beat":..,"beats":..}
连音线(tie): 合并成一个事件, sustain=True(按住整个时值)
"""
import json, sys
from collections import defaultdict

LETTER = {'1':'Z','2':'X','3':'C','4':'V','5':'B','6':'N','7':'M','i':','}

def dur_of(n):
    v = {0: 1.0, 1: 0.5, 2: 0.25}.get(min(n['ul'], 2), 0.25)
    return v * 1.5 if n['dot'] else v

def build(src='song_sys.json', out='score.json', bpm=125, beats_per_measure=4):
    data = json.load(open(src, encoding='utf-8'))
    measures = []
    for sd in data:
        bars = list(sd['bars']); groups = []; cur = []
        for i in range(len(sd['notes'])):
            x = sd['notes'][i]['x']
            while bars and bars[0] < x - 2:
                groups.append(cur); cur = []; bars.pop(0)
            cur.append(i)
        groups.append(cur)
        # tie 的第二个音 -> 合并
        tie2 = {t['j'] for t in sd['ties'] if t['tie']}   # 连音线的第二个音
        for g in groups:
            if not g: continue
            ev = []; t = 0.0
            for k, i in enumerate(g):
                n = sd['notes'][i]
                d = dur_of(n)
                key = None if n['digit'] == '0' else LETTER.get(str(n['digit']), '?')
                mods = []
                if n['sharp']: mods.append('middle')          # 中键 = 半音
                if n['oct'] > 0: mods.append('right')         # 右键 = 升调(高音)
                elif n['oct'] < 0: mods.append('left')
                sustain = False
                if i in tie2 and ev and ev[-1]['key'] == key:
                    ev[-1]['beats'] += d                     # 连音 -> 前一音延长
                    ev[-1]['sustain'] = True
                    t += d
                    continue
                ev.append(dict(key=key, mods=mods, beat=t, beats=d, sustain=False,
                               src=sorted(mods), note=f"{'#' if n['sharp'] else ''}{n['digit']}"))
                t += d
            measures.append(dict(line=[sd['page'] + 1, sd['sys'] + 1], events=ev,
                                 beats=round(t, 4)))
    total = sum(m['beats'] for m in measures)
    score = dict(bpm=bpm, beats_per_measure=beats_per_measure, total_beats=round(total, 3),
                 duration_sec=round(total * 60.0 / bpm, 1), measures=measures)
    json.dump(score, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    from collections import Counter
    c = Counter(round(m['beats'], 2) for m in measures)
    print(f"小节 {len(measures)}  总拍 {total:g}  ≈{score['duration_sec']}s @♩={bpm}")
    print("每小节拍数分布:", c.most_common(8))
    print(f"写出 {out}")
    return score

if __name__ == '__main__':
    build(*(sys.argv[1:] or []))
