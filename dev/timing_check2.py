#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timing_check2.py — 纯净时序测量（把注入换成空操作，只测调度）。

不真的发输入：不会打扰游戏，也能在游戏满载时照跑。
它核对三件事：
  1) 每个音「计划时刻 vs 真正到点调用的时刻」→ 调度迟到
  2) 相邻音起点间隔 → burst（几个键挤在同一瞬间）
  3) 修饰键提前量 / 按住时长是否满足游戏按帧采样的预算（见 play.TIMINGS）

用法: python timing_check2.py [起始小节] [结束小节] [档位]    默认 1 10 standard
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
import json, sys, time
import play

frm = int(sys.argv[1]) if len(sys.argv) > 1 else 1
to = int(sys.argv[2]) if len(sys.argv) > 2 else 10
timing = sys.argv[3] if len(sys.argv) > 3 else 'standard'

_os.chdir(_d)
score = json.load(open(_os.path.join('data', 'score2.json'), encoding='utf-8'))


class Args:
    bpm, pad, mode, countdown, lead = 125.0, False, 'hold', 0.0, 0.0
    from_measure, to_measure, dry_run, abort = frm, to, False, 'F10'
    late, late_tol, verbose_late, input = 'drop', 0.05, False, 'vk'
    timing, debug_timing, timing_log = timing, False, ''


plan, acts, total = play.build_timeline(score, Args())
exp = [p['kdn'] for p in plan]
print(f"计划：第 {frm}-{to} 小节，{len(plan)} 个音 / {len(acts)} 个动作，时长 {total:.1f}s，档位 {timing}")

# ---- 屏蔽真实注入，挂探针 ----
onsets, wakeups = [], []
_real_sleep_until = play.sleep_until


def sleep_until_probe(t):
    _real_sleep_until(t)
    wakeups.append((t, time.perf_counter()))


play.sleep_until = sleep_until_probe
play.key_down = lambda name: onsets.append((name, time.perf_counter()))
play.key_up = lambda *a, **k: None
play.mouse_down = play.mouse_up = lambda *a, **k: None

t_start = time.perf_counter()
play.play(score, Args())
wall = time.perf_counter() - t_start

print(f"\n===== 测量结果（{len(exp)} 个音，实耗 {wall:.1f}s，理论 {exp[-1] + plan[-1]['hold']:.1f}s）=====")
base = onsets[0][1] - exp[0] if onsets else 0
lat = [((t - base) - e) * 1000 for (n, t), e in zip(onsets, exp)]
dev = [abs(x) for x in lat]
print(f"捕获音数 {len(onsets)} / 期望 {len(exp)}")
if dev:
    print(f"偏差: 平均 {sum(dev)/len(dev):7.1f}ms  中位 {sorted(dev)[len(dev)//2]:7.1f}ms  最大 {max(dev):7.1f}ms")
    print(f"偏差>25ms 的音: {sum(1 for x in dev if x > 25)} / {len(dev)}   偏差>60ms: {sum(1 for x in dev if x > 60)}")
gaps = [(onsets[i + 1][1] - onsets[i][1]) * 1000 for i in range(len(onsets) - 1)]
burst = [i for i, g in enumerate(gaps) if g < 20]
print(f"相邻音起点间隔<20ms 的 burst: {len(burst)} 处 {burst[:12]}")
print(f"间隔不足乐谱期望一半的位置: {sum(1 for i, g in enumerate(gaps) if g < (exp[i+1]-exp[i])*1000*0.5)}")
wg = [(w, a) for w, a in wakeups if (a - w) > 0.025]
print(f"唤醒迟到>25ms 的次数: {len(wg)} / {len(wakeups)}；最坏 {max([(a-w)*1000 for w,a in wakeups], default=0):.1f}ms")
print("最差偏差(ms):", [round(x) for x in sorted(lat)[:3]], "...", [round(x) for x in sorted(lat)[-3:]])
if gaps:
    print(f"音间间隔(ms): 最小 {min(gaps):.0f} 中位 {sorted(gaps)[len(gaps)//2]:.0f} 最大 {max(gaps):.0f}")
