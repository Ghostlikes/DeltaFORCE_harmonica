#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""演奏提示条（HUD）：置顶半透明小窗，显示当前音 / 接下来几个音 / 进度。

对照两份参考实现做的：
  * ChickenD233/midikey-player 的 OverlayWindow —— 置顶、无边框、显示即将到来的按键
  * ChiZhou6/harmonica-visualizer —— 高亮当前音、显示变调键与键位

特点：**独立运行**。它只按时间轴自己走，不跟 play.py 耦合，所以
Python 播放器、导出的 AutoHotkey/G HUB 宏、甚至手动弹，都能用它看谱。

用法：
    python tools/hud.py --score data/score2.json   # 默认 125 BPM，倒计时 6 秒
    python hud.py --song songs/天空之城.jianpu      # 任意格式谱面
    python hud.py --score score2.json --countdown 8 --offset 0
    python hud.py --score score2.json --no-gui     # 只打印，不开窗（核对时间轴用）
"""

from __future__ import annotations
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

import argparse
import json
import os
import sys
import threading
import time

BAR = "─"


def load_events(args):
    """→ (标题, bpm, [(t秒, 显示文本, 是否变调, 时值秒)])"""
    if args.song:
        import score as sm
        sc = sm.parse_any(args.song)
        tab, _ = sm.to_score_table(sc)
        title, bpm = sc.title, sc.bpm
    else:
        tab = json.load(open(args.score, encoding="utf-8"))
        title, bpm = tab.get("title") or "未命名", float(tab.get("bpm") or 125)
    bpm = args.bpm or bpm
    beat = 60.0 / bpm
    per = float(tab.get("beats_per_measure") or 4.0)
    evs = []
    for mi, m in enumerate(tab.get("measures") or [], 1):
        base = (mi - 1) * per
        for ev in m.get("events") or []:
            t = (base + float(ev.get("beat") or 0.0)) * beat
            if not ev.get("key"):
                continue
            txt = "+".join(sorted(ev.get("mods") or [])) + ("+" if ev.get("mods") else "")
            face = {"left": "左", "middle": "中", "right": "右"}
            mods = "".join(face.get(x, x) for x in sorted(ev.get("mods") or []))
            evs.append((t, f"{ev['key']}{('[' + mods + ']') if mods else ''}",
                        bool(ev.get("mods")), float(ev.get("beats") or 1) * beat))
    return title, bpm, evs


def render_state(title, bpm, evs, now, args):
    idx = 0
    while idx < len(evs) and evs[idx][0] <= now:
        idx += 1
    cur = evs[idx - 1] if idx else None
    coming = evs[idx:idx + args.lookahead]
    total = evs[-1][0] if evs else 1.0
    pct = min(100.0, max(0.0, now / max(total, 0.001) * 100))
    barw = 28
    filled = int(barw * pct / 100)
    return {
        "title": f"{title} · ♩={bpm:g} · {len(evs)} 个音",
        "bar": f"[{'█' * filled}{BAR * (barw - filled)}] {pct:5.1f}%  {now:6.1f}s / {total:.1f}s",
        "cur": f"当前：{cur[1] if cur else '—'}" + (f"（时值 {cur[3] * 1000:.0f}ms）" if cur else ""),
        "next": "接下来：" + "  ".join(x[1] for x in coming) if coming else "接下来：—",
        "idx": f"{idx}/{len(evs)}",
    }


def run_gui(title, bpm, evs, args):
    import tkinter as tk
    root = tk.Tk()
    root.title("口琴提示条")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", args.alpha)
    except Exception:
        pass
    root.configure(bg="#101418")
    font = ("Microsoft YaHei UI", 11)
    lab_title = tk.Label(root, bg="#101418", fg="#8ab4f8", font=(font[0], 12, "bold"), anchor="w")
    lab_bar = tk.Label(root, bg="#101418", fg="#c9d1d9", font=("Consolas", 11), anchor="w")
    lab_cur = tk.Label(root, bg="#101418", fg="#7ee787", font=(font[0], 18, "bold"), anchor="w")
    lab_next = tk.Label(root, bg="#101418", fg="#e3b341", font=(font[0], 13), anchor="w")
    for w in (lab_title, lab_bar, lab_cur, lab_next):
        w.pack(fill="x", padx=14, pady=2)
    root.geometry(f"+{args.x}+{args.y}")

    def tick():
        now = time.perf_counter() - t0[0]
        st = render_state(title, bpm, evs, now, args)
        lab_title.config(text=st["title"])
        lab_bar.config(text=st["bar"] + "   " + st["idx"])
        lab_cur.config(text=st["cur"])
        lab_next.config(text=st["next"])
        if not args.loop and evs and now > evs[-1][0] + 3:
            root.destroy()
            return
        root.after(50, tick)

    print(f"提示条已开启（{args.countdown}s 后开始，节点 {args.x},{args.y}；关窗即退出）", flush=True)
    def start():
        rem = args.countdown
        while rem > 0:
            print(f"  {rem:g}...", flush=True)
            time.sleep(min(1.0, rem))
            rem -= 1.0
        t0[0] = time.perf_counter()
        print("开始 ♪", flush=True)
    t0 = [None]
    threading.Thread(target=lambda: (start(),), daemon=True).start()
    # 倒计时阶段先显示 0 时刻
    t0[0] = float("inf")
    def wait_then_tick():
        while t0[0] == float("inf"):
            time.sleep(0.1)
        tick()
    threading.Thread(target=wait_then_tick, daemon=True).start()
    root.mainloop()
    return 0


def run_headless(title, bpm, evs, args):
    """--no-gui：按时间轴打印（不按键、不开窗），用来核对每音之间的间隔。"""
    print(f"{title} · ♩={bpm:g} · {len(evs)} 个音")
    prev = None
    for t, txt, mods, dur in evs:
        gap = "" if prev is None else f" 距上一音 {(t - prev) * 1000:6.0f}ms"
        print(f"{t:8.3f}s  {txt:14s} 时值 {dur * 1000:6.0f}ms{gap}  {'变调键' if mods else ''}")
        prev = t
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--score', default=os.path.normpath(os.path.join(_d, 'data', 'score2.json')))
    ap.add_argument('--song', default='', help='任意格式谱面（.jianpu/.txt/.mid），优先于 --score')
    ap.add_argument('--bpm', type=float, default=0, help='0 = 用谱面自带')
    ap.add_argument('--countdown', type=float, default=6)
    ap.add_argument('--offset', type=float, default=0, help='整体提前/延后多少秒（对齐宏用）')
    ap.add_argument('--lookahead', type=int, default=4)
    ap.add_argument('--alpha', type=float, default=0.85)
    ap.add_argument('--x', type=int, default=40)
    ap.add_argument('--y', type=int, default=40)
    ap.add_argument('--loop', action='store_true', help='弹完不自动关窗')
    ap.add_argument('--no-gui', action='store_true', help='只打印时间轴，不开窗')
    args = ap.parse_args()
    if not os.path.exists(args.song or args.score):
        sys.exit(f"找不到谱面：{args.song or args.score}")
    title, bpm, evs = load_events(args)
    if args.offset:
        evs = [(max(0.0, t + args.offset), a, b, c) for t, a, b, c in evs]
    if args.no_gui:
        return run_headless(title, bpm, evs, args)
    return run_gui(title, bpm, evs, args)


if __name__ == '__main__':
    main()
