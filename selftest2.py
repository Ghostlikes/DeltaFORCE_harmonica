#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest2.py — 单进程端到端自检：抢到前台焦点后，用 play.py 的注入函数发送
   一组 中键/右键 + 字母键，并回读 Tk 窗口收到的键与鼠标事件。

用法: python selftest2.py [输入方式 vk|scan|both]
"""
import ctypes, sys, time, tkinter as tk
import play

user32 = ctypes.windll.user32
mode = sys.argv[1] if len(sys.argv) > 1 else 'vk'
play.INPUT_MODE[0] = mode

events = []
root = tk.Tk()
root.title("selftest2")
root.geometry("460x180+500+350")
root.attributes("-topmost", True)
ent = tk.Entry(root, font=("Consolas", 20))
ent.pack(expand=True, fill="both", padx=20, pady=20)
root.bind("<Key>", lambda e: events.append(("key", e.keysym)))
root.bind("<Button>", lambda e: events.append(("mouse", e.num)))
root.update()
hwnd = int(root.frame(), 16) if isinstance(root.frame(), str) else int(root.frame())

# 抢焦点直到本窗口成为前台窗口
t0 = time.time()
while time.time() - t0 < 15:
    root.update()
    root.focus_force()
    ent.focus_set()
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        break
    time.sleep(0.2)
fg = user32.GetForegroundWindow()
print(f"[selftest2] mode={mode} hwnd={hwnd} fg={fg} focused={fg==hwnd}")
if fg != hwnd:
    print("[selftest2] 未取得前台焦点，测试结果不可信（游戏/其它窗口抢占）")
    root.destroy(); sys.exit(1)

# 光标移到窗口中心，保证鼠标按键落在本窗口
x = root.winfo_rootx() + root.winfo_width() // 2
y = root.winfo_rooty() + root.winfo_height() // 2
user32.SetCursorPos(int(x), int(y))
root.update()
time.sleep(0.3)

# 注入：中键+E? 用真实曲谱片段(中键+V 等)
tests = [({'key': 'V', 'mods': ['middle']}, 'hold', 0.05),
         ({'key': 'C', 'mods': ['middle', 'right']}, 'hold', 0.05),
         ({'key': 'Z', 'mods': []}, 'hold', 0.05)]
print("[selftest2] 注入中键+V、中键+右键+C、Z ...")
for ev, m, h in tests:
    play.press(ev, m, h)
    root.update()
    time.sleep(0.25)
root.update()
time.sleep(0.4)
root.update()

txt = ent.get()
print(f"[selftest2] Entry 收到的字符: {txt!r}")
print(f"[selftest2] 事件序列: {events}")
ok_key = 'ZC' in txt or 'zvc' in txt.lower()
ok_mouse = any(k == 'mouse' and v in (2, 3) for k, v in events)
print(f"[selftest2] 键盘送达={'是' if ok_key else '否'}  鼠标送达={'是' if ok_mouse else '否'}")
root.destroy()
