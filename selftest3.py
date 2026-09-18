#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端自检：解析 → 换算按键 → 建时间轴 → 校验不变量 → 导出宏 → 往返比对。

不发任何按键（ACE 反作弊会屏蔽全局钩子，注入类自检请另跑 selftest2.py）。
用法：python selftest3.py [谱面路径...]   默认扫 songs/ 与 midikey 示例 MIDI。
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

import keymap
import macros
import score as sm

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'✔' if cond else '✗'} {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def one(path):
    print(f"\n=== {os.path.basename(path)} ===")
    sc = sm.parse_any(path)
    check("解析出音符", len(sc.notes) > 0, f"{len(sc.notes)} 个音 · {sc.fmt} · {sc.bpm:g}BPM")
    tab, st = sm.to_score_table(sc)
    check("换算成按键", st["playable"] > 0,
          f"可弹 {st['playable']}/{st['notes']} · 基准八度 {st['base_octave']}")
    check("音域自洽", keymap.in_range(st["hi"]) or st["out_of_range"] > 0,
          f"音域 {st['lo']}..{st['hi']}，越界 {st['out_of_range']}")
    # 时间轴 + 不变量（直接复用 play.build_timeline）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import play

    class A:
        timing, bpm, pad = "standard", sc.bpm, False
        from_measure, to_measure = 1, 10 ** 9
    A.bpm = sc.bpm
    plan, acts, total = play.build_timeline(tab, A())
    upstream = all(acts[i][0] <= acts[i + 1][0] + 1e-9 for i in range(len(acts) - 1))
    check("动作时间不倒退", upstream, f"{len(acts)} 个动作")
    check("音序与谱面一致", len(plan) == st["playable"], f"{len(plan)} 个音")
    gaps = [round((plan[i + 1]["t"] - plan[i]["t"]) * 1000) for i in range(len(plan) - 1)]
    check("没有连发的音（<20ms 间隔）", all(g >= 20 for g in gaps) or not gaps,
          f"最小间隔 {min(gaps) if gaps else '-'}ms")
    check("每个音都按住了（≥一帧）", all(p["hold"] > 0.016 for p in plan),
          f"最短按住 {min((p['hold'] for p in plan), default=0) * 1000:.0f}ms")
    # 简谱往返
    txt = sm.format_jianpu(sc)
    back = sm.parse_any(path, text=txt)
    pa = [(n.pitch, round(n.start, 3), round(n.dur, 3)) for n in sc.notes]
    pb = [(n.pitch, round(n.start, 3), round(n.dur, 3)) for n in back.notes]
    same = sum(1 for x, y in zip(pa, pb) if x == y)
    check("简谱导出→重解析", same >= len(pa) - max(1, len(pa) // 20),
          f"{same}/{len(pa)} 个音完全一致")
    # 导出四种宏
    d = tempfile.mkdtemp(prefix="harmonica_selftest_")
    for fmt in ("csv", "timeline", "ahk", "lua"):
        f = os.path.join(d, f"x.{fmt if fmt != 'timeline' else 'txt'}")
        {"csv": macros.export_csv, "timeline": macros.export_timeline,
         "ahk": macros.export_ahk, "lua": macros.export_lua}[fmt](plan, acts, f)
        check(f"导出 {fmt}", os.path.getsize(f) > 200, f"{os.path.getsize(f)} 字节")
    # 事件表落盘后用独立校验器再验一遍
    sj = os.path.join(d, "t.json")
    json.dump(tab, open(sj, "w", encoding="utf-8"), ensure_ascii=False)
    r = subprocess.run([sys.executable, "check_invariants.py", sj, "standard"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0 and "✗" not in (r.stdout or "")
    check("独立校验器 check_invariants", ok, (r.stdout or r.stderr or "").strip().splitlines()[-1][:80])


def main():
    paths = sys.argv[1:]
    if not paths:
        paths = sorted(glob.glob("songs/*.jianpu") + glob.glob("songs/*.txt")
                       + glob.glob("refs/midikey/示例MIDI/*.mid"))
    print(f"端到端自检：{len(paths)} 个谱面（不发按键）")
    for p in paths:
        try:
            one(p)
        except Exception as e:
            import traceback
            traceback.print_exc()
            FAIL.append(f"{os.path.basename(p)} 抛异常 {type(e).__name__}")
    print(f"\n{'='*60}\n结果：{'全部通过 ✔' if not FAIL else '失败 ' + str(len(FAIL)) + ' 项：' + '; '.join(FAIL[:6])}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
