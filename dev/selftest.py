#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py — 验证 play.py 注入的键盘/鼠标事件是否真的到达前台窗口。

用法: python selftest.py <持续秒数>
会弹出置顶窗口并抢占焦点，记录所有 Key / Button 事件后打印。
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
import sys, time, tkinter as tk

dur = float(sys.argv[1]) if len(sys.argv) > 1 else 12
events = []
t0 = None

root = tk.Tk()
root.title("input selftest")
root.attributes("-topmost", True)
root.geometry("420x160+400+300")
tk.Label(root, text="自检窗口：正在接收输入…", font=("Microsoft YaHei", 13)).pack(expand=True)


def on_key(e):
    events.append(("key", e.keysym, round(time.time() - t0, 3)))


def on_btn(e):
    events.append(("mouse", e.num, round(time.time() - t0, 3)))


root.bind("<Key>", on_key)
root.bind("<Button>", on_btn)
root.bind("<ButtonRelease>", lambda e: None)


def start():
    global t0
    root.focus_force()
    root.lift()
    root.attributes("-topmost", True)
    # 把鼠标移到窗口中心，确保鼠标按键事件落在本窗口
    x = root.winfo_rootx() + root.winfo_width() // 2
    y = root.winfo_rooty() + root.winfo_height() // 2
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    t0 = time.time()
    print(f"[selftest] 焦点窗口={root.focus_displayof()} t0={t0:.3f}", flush=True)
    keep_focus()


def keep_focus():
    if time.time() - t0 < dur:
        if root.focus_displayof() is None:
            print(f"[selftest] {time.time()-t0:.2f}s 失去焦点，重新抢占", flush=True)
            root.focus_force()
        root.after(250, keep_focus)


import ctypes


def diag():
    if t0 is None or time.time() - t0 > dur: return
    fg = ctypes.windll.user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(128)
    ctypes.windll.user32.GetWindowTextW(fg, buf, 128)
    print(f"[diag] {time.time()-t0:5.2f}s fg={fg} title={buf.value!r} events={len(events)}", flush=True)
    root.after(500, diag)


root.after(300, start)
root.after(600, diag)
root.after(int(dur * 1000), root.destroy)
root.mainloop()

print(f"共收到 {len(events)} 个输入事件:")
for kind, what, t in events:
    print(f"   {t:7.3f}s  {kind:5s}  {what}")
