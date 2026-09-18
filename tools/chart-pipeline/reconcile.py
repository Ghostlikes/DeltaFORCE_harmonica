import json

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
from collections import defaultdict
sd = json.load(open('song_sys.json', encoding='utf-8'))
sc = json.load(open('score.json', encoding='utf-8'))
src = defaultdict(lambda: [0, 0])          # (page,sys) -> [notes, ties]
for s in sd:
    src[(s['page'], s['sys'])][0] = len(s['notes'])
    src[(s['page'], s['sys'])][1] = sum(1 for t in s['ties'] if t['tie'])
ev_out = defaultdict(int)
for m in sc['measures']:
    ev_out[tuple(x-1 for x in m['line'])] += len(m['events'])
tot_src = tot_tie = tot_out = 0
bad = []
for k in sorted(src):
    n, tie = src[k]
    o = ev_out.get(k, 0)
    tot_src += n; tot_tie += tie; tot_out += o
    if n - tie != o:
        bad.append((k, n, tie, o, n - tie - o))
print(f"源音符总数 {tot_src}  - 连音合并 {tot_tie}  = 应有事件 {tot_src-tot_tie}   实际事件 {tot_out}   差 {tot_src-tot_tie-tot_out}")
print(f"对不上的行数: {len(bad)} / {len(src)}")
for k, n, tie, o, d in bad[:20]:
    print(f"  页{k[0]+1} 行{k[1]+1}: 音符{n} - 连音{tie} = {n-tie}  实际{o}  丢失{d}")
