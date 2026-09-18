"""Emit playable ops for the whole song from song_sys.json (+ jianpu transcription)."""

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
import json, sys
from collections import Counter

LETTER = {'1': 'Z', '2': 'X', '3': 'C', '4': 'V', '5': 'B', '6': 'N', '7': 'M', 'i': ','}
D2L = {v: k for k, v in LETTER.items()}
SEMI, UP, DOWN = '中键', '右键', '左键'

def dur_of(n):
    v = {0: 1.0, 1: 0.5, 2: 0.25}.get(min(n['ul'], 2), 0.25)
    return v * 1.5 if n['dot'] else v

def measures_of(sd):
    bars = list(sd['bars']); out = []; cur = []
    for i in range(len(sd['notes'])):
        x = sd['notes'][i]['x']
        while bars and bars[0] < x - 2:
            out.append(cur); cur = []; bars.pop(0)
        cur.append(i)
    out.append(cur)
    return [m for m in out if m]

def main():
    data = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'song_sys.json'))
    md = ['# 三角洲行动 口琴玩法 —— 《I Really Want to Stay at Your House》按键操作',
          '',
          '**曲谱来源**：玩家自制简谱（固定调，♩=125，4/4）',
          '',
          '**键位映射**：`Z X C V B N M ,` = `1 2 3 4 5 6 7 i(高音1)`；'
          '**鼠标**：中键=半音(对应简谱 `#`)、右键=升调(高音，对应简谱 `(V)`)、左键=降调(低音)',
          '',
          '**记号**：`半` = 按中键半音 · `↑` = 按右键升调 · `↓` = 按左键降调 · '
          '`↷` = 与前音同音连音，只需按住不重复按 · `休` = 休止',
          '']
    jp_lines = []
    total_notes = total_rests = total_beats = 0
    tie_second = set()
    for sd in data:
        for t in sd['ties']:
            if t['tie']:
                tie_second.add((sd['page'], sd['sys'], t['j']))
    for sd in data:
        ms = measures_of(sd)
        if not ms: continue
        md.append(f"### 第 {sd['page']+1} 页 · 第 {sd['sys']+1} 行")
        jpline = []
        for mi, m in enumerate(ms, 1):
            parts = []; jparts = []
            for k, i in enumerate(m):
                n = sd['notes'][i]
                beats = dur_of(n)
                total_beats += beats
                jp = ('#' if n['sharp'] else '') + str(n['digit'])
                if n['oct'] > 0: jp += "'" * n['oct']
                if n['oct'] < 0: jp += '͟' * (-n['oct'])
                if n['dot']: jp += '.'
                jp += '_' * n['ul']
                jparts.append(jp)
                if n['digit'] == '0':
                    parts.append(f'休({beats:g})')
                    total_rests += 1
                    continue
                total_notes += 1
                # key letter: prefer the sheet's own annotation
                ks = [g for g in sd['keys'] if g['kind'] == 'key'
                      and abs((g['x0'] + g['x1']) / 2 - n['x']) < 20]
                g = min(ks, key=lambda g: abs((g['x0'] + g['x1']) / 2 - n['x'])) if ks else None
                letter = LETTER.get(str(n['digit']), '?')      # 由简谱数字推导键位
                octv = 1 if n['oct'] > 0 else 0                   # 由高音点推导八度
                if g and g['label'] != letter:
                    letter = g['label'] if g['dist'] < 0.15 and n['dist'] > 0.15 else letter
                ops = []
                if n['sharp']: ops.append(SEMI)
                if octv > 0: ops.append(UP)
                elif n['oct'] < 0: ops.append(DOWN)
                ops.append(letter)
                tied = (sd['page'], sd['sys'], i) in tie_second
                s = '+'.join(ops) + (f'({beats:g})' if not tied else f'(↷{beats:g})')
                if tied: s = '↷' + s
                parts.append(s)
            jp_lines.append('| ' + ' '.join(jparts) + ' |')
            md.append(f"- **第{mi}小节**（{sum(dur_of(sd['notes'][i]) for i in m):g}拍）: "
                      + '  →  '.join(parts))
        jp_lines.append('')
        md.append('')
    open('song_ops.md', 'w', encoding='utf-8').write('\n'.join(md))
    open('song_jianpu.txt', 'w', encoding='utf-8').write('\n'.join(jp_lines))
    print(f"systems={len(data)} notes={total_notes} rests={total_rests} beats={total_beats:g} "
          f"(≈{total_beats*60/125:.0f}s at ♩=125)")
    ms_sums = Counter()
    for sd in data:
        for m in measures_of(sd):
            ms_sums[round(sum(dur_of(sd['notes'][i]) for i in m), 2)] += 1
    print("measure-length histogram:", ms_sums.most_common(8))
    print("measures:", sum(ms_sums.values()))

if __name__ == '__main__':
    main()
