#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_invariants.py — 全曲数据级不变量校验（不发任何输入）。

校验项：
  1) 动作时间严格不倒退，同一时刻只有「松」在「按」之前
  2) 任何时刻同一个音键不会重复按下（不会出现"还没松手就按下一个音"）
  3) 每个音按下时，按住的修饰键集合恰好等于该音需要的集合（音高正确性的必要条件）
  4) 每个音按住时长 >= 档位最短按住；前音抬起→后音按下 >= 抬起余量（帧采样预算）
  5) 修饰键状态变化不与音键按下落在同一时刻
  6) 同键重触发间隔 >= 重触发阈值
用法: python dev/check_invariants.py [data/score2.json] [档位]
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
import json, sys
import play

_os.chdir(_d)                     # 切到项目根，data/、songs/ 相对路径才成立
path = sys.argv[1] if len(sys.argv) > 1 else _os.path.join('data', 'score2.json')
timing = sys.argv[2] if len(sys.argv) > 2 else 'standard'
T = play.TIMINGS[timing]


class A:
    bpm, pad, mode, from_measure, to_measure = 125.0, False, 'hold', 1, 10 ** 9
    timing = timing
    countdown, lead, late, late_tol, verbose_late, input = 0, 0.0, 'drop', 0.05, False, 'vk'
    dry_run, debug_timing, timing_log, abort, score, calib = False, False, '', 'F10', path, False


score = json.load(open(path, encoding='utf-8'))
plan, acts, total = play.build_timeline(score, A())
print(f"{path}（档位 {timing}）：音 {len(plan)} 个 / 动作 {len(acts)} 个 / 总时长 {total:.2f}s")

bad = []
held_keys, held_mods = set(), set()
prev_t = -1.0
last_kdn, last_kup = {}, {}
for t, kind, arg, nidx in acts:
    if t < prev_t - 1e-9:
        bad.append(("时间倒退", t, kind, arg))
    prev_t = max(prev_t, t)
    if kind == 'kdn':
        if arg in held_keys:
            bad.append(("键未松开就重按", round(t, 4), arg))
        p = plan[nidx]
        if held_mods != set(p['mods']):
            bad.append(("按下时修饰键不匹配", round(t, 4), f"{arg}: 实际{sorted(held_mods)} 需要{p['mods']}"))
        if nidx in last_kdn and (t - last_kdn[nidx]) < 0:
            bad.append(("同键重触发次序异常", round(t, 4), arg))
        held_keys.add(arg)
        last_kdn[nidx] = t
    elif kind == 'kup':
        if arg not in held_keys:
            bad.append(("松开未按下的键", round(t, 4), arg))
        held_keys.discard(arg)
        last_kup[nidx] = t
        p = plan[nidx]
        hold = t - p['kdn']
        if hold < T['min_hold'] / 1000.0 - 1e-9:
            bad.append(("按住过短", round(q := hold * 1000, 1), f"{arg} < {T['min_hold']}ms"))
    elif kind == 'mdn':
        held_mods.add(arg)
    elif kind == 'mup':
        held_mods.discard(arg)

# 相邻音：前音抬起 → 后音按下
for i in range(1, len(plan)):
    a, b = plan[i - 1], plan[i]
    if a['key'] and b['key']:
        gap = (b['kdn'] - a['kup']) * 1000
        need = T['release_gap'] - 8.5 if b['change'] else T['release_gap']
        if gap < need - 1e-6:
            bad.append(("抬起→按下间隔不足", i, f"{gap:.1f}ms < {need:.1f}ms"))

# 修饰键变化不与音键同刻
for t, kind, arg, nidx in acts:
    if kind == 'mdn':
        for p in plan:
            if abs(p['kdn'] - t) < 1e-6 and arg in p['mods']:
                bad.append(("修饰键与音键同刻", round(t, 4), arg))

# 同键重触发
# 口径必须是「上一次同一个键抬起 → 这一次按下」。用「按下→按下」会把按住的那段时间算进去，
# 26ms 的真实间隔会被报成 250ms，这类缺音就查不出来了（暗号开头连击 riff 就是这么漏掉的）。
last_up = {}
for i, p in enumerate(plan):
    if not p['key']:
        continue
    if p['key'] in last_up:
        d = (p['kdn'] - last_up[p['key']]) * 1000
        # 阈值比较留 1e-6 容差：计划里间隔正好等于阈值时，浮点会算成 44.999999…
        if d < T['retrigger'] - 1e-6:
            bad.append(("同键重触发过密", i, f"{p['key']} 抬→按 {d:.1f}ms < {T['retrigger']}ms"))
    last_up[p['key']] = p['kup']

print(f"不变量检查：{'全部通过 ✔' if not bad else f'{len(bad)} 处异常'}")
for b in bad[:20]:
    print("   ", b)
print(f"最长按住 {max((p['hold'] for p in plan), default=0)*1000:.0f}ms"
      f" / 最短 {min((p['hold'] for p in plan), default=0)*1000:.0f}ms")
