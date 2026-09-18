#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机配置：刷新率/帧率 → 时序档位。首次运行时问一次，之后记住。

为什么时序跟帧率有关
--------------------
目标程序按帧采样输入，所以「修饰键先按下多久」「一个音至少按住多久」「抬起到下一次按下
隔多久」这些物理毫秒预算，本质上都是**帧长**的倍数。上游 MidiKeyPlayer 的
Engine/InputTiming.cs 给的就是三个固定档位：

    档位          帧长     修饰键提前   最短按住   抬-按间隔   推算比例
    60fps(标准)   16.7ms   40ms        45ms      40ms       2.4 / 2.7 / 2.4
    30fps(稳健)   33.3ms   70ms        80ms      70ms       2.1 / 2.4 / 2.1
    高刷(极限)     6.9ms   20ms        22ms      18ms       2.9 / 3.2 / 2.6

比例基本一致 → 所以任意帧率都能按「帧长 × 2.4 / 2.7 / 2.4」算出来，并设下限
（20/22/18ms，防止高刷时把预算压到比一帧还小）。这样 60fps 会精确还原上游的
40/45/40，144fps 精确还原 20/22/18 —— 两端口都对得上，中间帧率自然可信。
"""
import ctypes
import json
import os

CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.harmonica_config.json')
DEFAULT_FPS = 60.0

RATIO_LEAD, RATIO_HOLD, RATIO_GAP = 2.4, 2.7, 2.4
FLOOR_LEAD, FLOOR_HOLD, FLOOR_GAP = 20, 22, 18


def profile_for(fps) -> dict:
    """帧率 → 时序档位（物理毫秒）。"""
    fps = max(10.0, min(1000.0, float(fps)))
    frame = 1000.0 / fps
    return dict(
        name=f'{fps:g}Hz 按帧率自适应',
        fps=fps,
        frame=round(frame, 2),
        mod_lead=max(FLOOR_LEAD, round(frame * RATIO_LEAD)),
        min_hold=max(FLOOR_HOLD, round(frame * RATIO_HOLD)),
        release_gap=max(FLOOR_GAP, round(frame * RATIO_GAP)),
        # 起步提前量：上游 _leadSec = max(LeadMs, ModLeadMs + FrameMs) —— 57≈40+16.7、
        # 104≈70+33.3、28=20+8，三个档位都吻合。
        lead_ms=round(max(FLOOR_LEAD, round(frame * RATIO_LEAD)) + frame),
    )


def detect_refresh_rate():
    """主显示器的刷新率（Hz）。拿不到返回 None。

    用 GetDeviceCaps(hdc, VREFRESH)：全屏独占游戏实际就是按显示器刷新率跑的；
    如果游戏内帧率更高（无上限）或更低（锁帧），用户按实际值填即可。
    """
    try:
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        hdc = user32.GetDC(0)
        if not hdc:
            return None
        try:
            hz = int(gdi32.GetDeviceCaps(hdc, 116))          # VREFRESH = 116
        finally:
            user32.ReleaseDC(0, hdc)
        return hz if 10 <= hz <= 1000 else None
    except Exception:
        return None


def load() -> dict:
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(d: dict) -> bool:
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


if __name__ == '__main__':
    print('配置文件:', CONFIG_PATH, '→', load() or '（还没有）')
    print('检测到刷新率:', detect_refresh_rate(), 'Hz')
    for f in (30, 60, 90, 120, 144, 165, 240):
        p = profile_for(f)
        print(f"  {f:>3}Hz  帧长{p['frame']:>5}ms  修饰提前{p['mod_lead']:>3}ms  "
              f"最短按住{p['min_hold']:>3}ms  抬-按{p['release_gap']:>3}ms")
