import json
from collections import Counter
s = json.load(open('score.json', encoding='utf-8'))
bpm_m = s['beats_per_measure']
print("拍号:", bpm_m, " 小节数:", len(s['measures']))

# 第1-8小节的音位置(小节内拍)
for mi, m in enumerate(s['measures'][:8], 1):
    ev = [(e['beat'], e['beats'], e['key']) for e in m['events'] if e['key']]
    print(f"  小节{mi:3d} 内容共{m['beats']:>4}拍: " +
          "  ".join(f"{k}@{b:g}({d:g}拍)" for b, d, k in ev))

# 全曲绝对起拍序列（小时值）+ 间隔
absb, cur = [], 0.0
for m in s['measures']:
    for e in m['events']:
        if e['key']:
            absb.append(cur + e['beat'])
    cur += max(m['beats'], bpm_m)          # 与 --pad 一致
gaps = [round(absb[i+1]-absb[i], 3) for i in range(len(absb)-1)]
print("\n全曲音数:", len(absb), " 间隔(拍)分布 top:", Counter(gaps).most_common(8))

# 找"连续 2~3 个小间隔 + 1 个大间隔"的重复型（=听感上的 ABC 缓 DE 缓 FG）
big = 3.0
pattern = ''.join('s' if g < 1.0 else 'B' for g in gaps)
import re
runs = re.findall(r's{2,4}B', pattern)
print("小间隔串+大间隔 的组合出现次数:", len(runs), " 例:", Counter(runs).most_common(5))

# 每小节音数分布
n_notes = [sum(1 for e in m['events'] if e['key']) for m in s['measures']]
print("每小节音数分布:", Counter(n_notes).most_common())
short = [(i+1, m['beats'], sum(1 for e in m['events'] if e['key'])) for i, m in enumerate(s['measures']) if m['beats'] < bpm_m]
print(f"内容不足{4}拍的小节: {len(short)} 个 ->", short[:12])
