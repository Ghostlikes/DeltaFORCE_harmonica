#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timing_check.py — 真实注入路径的无干扰时序测量。

装 WH_KEYBOARD_LL / WH_MOUSE_LL 全局钩子，只拦截「注入型」事件（LLKHF_INJECTED/
LLMHF_INJECTED），记下到达时间戳后 **吞掉**（return 1），因此没有任何窗口/游戏会
收到这些输入 —— 不打扰你正在玩的游戏，同时测的又是 play.py 真正走的注入路径。

用法: python timing_check.py [起始小节] [结束小节]    默认 1 4
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
import ctypes, ctypes.wintypes as wt, json, sys, threading, time

import play

user32 = ctypes.WinDLL('user32', use_last_error=True)
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN = 0x0201, 0x0204, 0x0207
LLKHF_INJECTED, LLMHF_INJECTED = 0x00000010, 0x00000001
LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', wt.DWORD), ('scanCode', wt.DWORD), ('flags', wt.DWORD),
                ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('pt', wt.POINT), ('mouseData', wt.DWORD), ('flags', wt.DWORD),
                ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]


user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wt.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), ctypes.c_void_p, wt.UINT, wt.UINT, wt.UINT]

KB_NAME = {0x2C: 'Z', 0x2D: 'X', 0x2E: 'C', 0x2F: 'V', 0x30: 'B', 0x31: 'N', 0x32: 'M', 0x33: ','}
records, lock = [], threading.Lock()
stop = threading.Event()


def _log(kind, detail):
    with lock:
        records.append((kind, detail, time.perf_counter()))


def kb_proc(nCode, wParam, lParam):
    if nCode == 0:
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if kb.flags & LLKHF_INJECTED:
            name = KB_NAME.get(kb.scanCode, f'?0x{kb.scanCode:02X}')
            if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                _log('kdn', name)
            else:
                _log('kup', name)
            return 1                                  # 吞掉：不投递给任何窗口
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def ms_proc(nCode, wParam, lParam):
    if nCode == 0:
        ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        if ms.flags & LLMHF_INJECTED:
            if wParam == WM_MBUTTONDOWN:
                _log('mdn', 'middle')
            elif wParam == WM_RBUTTONDOWN:
                _log('mdn', 'right')
            elif wParam == WM_LBUTTONDOWN:
                _log('mdn', 'left')
            else:
                _log('mup', '')
            return 1
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


_kbproc, _msproc = HOOKPROC(kb_proc), HOOKPROC(ms_proc)


def main():
    frm = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    to = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    score = json.load(open(_os.path.join(_d, 'data', 'score.json'), encoding='utf-8'))

    class Args:
        bpm, pad, mode, countdown, lead = 125.0, True, 'hold', 0.0, 0.2
        from_measure, to_measure, dry_run, abort = frm, to, False, 'F10'
        late, late_tol, verbose_late, input = 'drop', 0.05, False, 'vk'

    notes, acts, total = play.build_timeline(score, Args())
    exp = [t for t, _, ev, _ in notes if ev['key'] is not None]
    print(f"[timing] 期望 {len(exp)} 个音（第 {frm}-{to} 小节，{total:.1f}s 内）")

    hkb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kbproc, None, 0)
    hms = user32.SetWindowsHookExW(WH_MOUSE_LL, _msproc, None, 0)
    print(f"[timing] 钩子 hkb={hkb} hms={hms}")
    if not hkb or not hms:
        print("[timing] 钩子安装失败 err=", ctypes.get_last_error()); return 1

    th = threading.Thread(target=lambda: play.play(score, Args()), daemon=True)
    th.start()

    msg = wt.MSG()
    t_end = time.time() + 300
    while th.is_alive() and time.time() < t_end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.001)
    th.join(timeout=5)
    user32.UnhookWindowsHookEx(hkb); user32.UnhookWindowsHookEx(hms)

    kd = [(d, t) for k, d, t in records if k == 'kdn']
    md = [(d, t) for k, d, t in records if k == 'mdn']
    print(f"[timing] 捕获: 键盘按下 {len(kd)} / 鼠标按下 {len(md)} / 总记录 {len(records)}")
    if not kd:
        return 1
    base = kd[0][1] - exp[0] - 0.2 + 0.2        # play() 内部 base 相对首个动作
    lat = [(t - kd[0][1]) - (e - exp[0]) for (d, t), e in zip(kd, exp)]
    dev = [abs(x) * 1000 for x in lat]
    print(f"[timing] 键盘音偏差: 平均 {sum(dev)/len(dev):.1f}ms  最大 {max(dev):.1f}ms"
          f"  >25ms: {sum(1 for x in dev if x > 25)}/{len(dev)}")
    gaps = [(kd[i + 1][1] - kd[i][1]) * 1000 for i in range(len(kd) - 1)]
    eg = [(exp[i + 1] - exp[i]) * 1000 for i in range(len(exp) - 1)]
    print(f"[timing] burst(相邻间隔<20ms): {sum(1 for g in gaps if g < 20)} 处")
    print(f"[timing] 相邻间隔 实际前10: {[round(g) for g in gaps[:10]]}")
    print(f"[timing] 相邻间隔 期望前10: {[round(g) for g in eg[:10]]}")
    # 鼠标/键盘是否重叠：检查每个音是不是 mdn → kdn → kup → (mup)
    seq = [(k, d) for k, d, _ in records][:14]
    print("[timing] 前 14 个事件顺序:", seq)
    return 0


if __name__ == '__main__':
    sys.exit(main())
