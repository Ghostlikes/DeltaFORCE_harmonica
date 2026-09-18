#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宏导出（照搬 midikey-player 的 MacroExporter.cs）：AutoHotkey / 罗技 G HUB Lua / CSV / 时间线。

时间线一律是「相对起弹毫秒」，并做误差进位，保证宏里绝不出现时间倒流。
"""


# ================================================================ 宏导出
def _flat(plan, acts):
    """动作队列 → 相对毫秒的扁平表（照搬 MacroExporter 的「误差进位」思路）。"""
    rows, last = [], 0.0
    for t, kind, arg, idx in acts:
        ms = int(round(t * 1000))
        if ms < last:
            ms = last                      # 误差进位：绝不允许时间倒流
        rows.append((ms, kind, arg, idx))
        last = ms
    return rows


def export_csv(plan, acts, path):
    """相对时间(ms),动作,对象,音序号 —— 表格化，方便自己核对/改。"""
    rows = _flat(plan, acts)
    label = {"mdn": "按下修饰键", "mup": "松开修饰键", "kdn": "按下音键", "kup": "松开音键"}
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("时刻ms,动作,对象,音序号\n")
        for ms, kind, arg, idx in rows:
            name = label.get(kind, kind)
            f.write("%d,%s,%s,%s\n" % (ms, name, arg, "" if idx is None else idx + 1))
    return path


def export_timeline(plan, acts, path):
    """人类可读时间线（对齐站点「事件时间线」：按键时刻 / 变调键 / 按住时长 / 气口）。"""
    rows = _flat(plan, acts)
    lines = ["# 时刻ms\t动作\t对象\t音\t修饰键\t按住ms\t与上一音间隔ms"]
    prev_end = None
    for p in plan:
        gap = "" if prev_end is None else f"{(p['t'] - prev_end) * 1000:.0f}"
        lines.append(f"{p['kdn']*1000:8.0f}\t按下\t{p['key']}\t{p.get('note') or ''}\t"
                     f"{'+'.join(p['mods']) or '无'}\t{p['hold']*1000:.0f}\t{gap}")
        prev_end = p['kup']
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")
    return path


def export_lua(plan, acts, path, name="三角洲口琴"):
    """罗技 G HUB 宏（Lua）：GHUB → 游戏与应用程序 → 新建 Lua 脚本 → 粘贴运行。"""
    rows = _flat(plan, acts)
    data = ";".join("%d,%s,%s" % (ms, kind, arg) for ms, kind, arg, _ in rows)
    lead = int(plan[0]['kdn'] * 1000) if plan else 0
    tpl = """-- __NAME__ · 自动演奏宏（由 harmonica/play.py 生成）
-- 用法：Logitech G HUB → 游戏与应用程序 → 你的三角洲配置 → 新建 Lua 脚本 → 全选替换 → 保存 → 绑定到鼠标侧键
-- 时间单位毫秒，已做「误差进位」，不会出现时间倒流。GHUB 里靠绑定侧键触发（绑到 MOUSE_BUTTON_PRESSED arg==4）。
local DATA = "__DATA__"
local LEAD = __LEAD__      -- 起弹后第一个音的延时（= 修饰键提前量，不是倒计时）

local function act(kind, arg)
  local down = (kind == "kdn" or kind == "mdn")
  if arg == "left" then
    if down then PressMouseButton(1) else ReleaseMouseButton(1) end
  elseif arg == "right" then
    if down then PressMouseButton(2) else ReleaseMouseButton(2) end
  elseif arg == "middle" then
    if down then PressMouseButton(3) else ReleaseMouseButton(3) end
  else
    if down then PressKey(arg) else ReleaseKey(arg) end
  end
end

-- 精确定时：GHUB 的 Sleep 会漂，这里用 GetRunningTime 忙等到点
local function run()
  local t0 = GetRunningTime()
  local target = LEAD
  for chunk in string.gmatch(DATA, "[^;]+") do
    local ms, kind, key = string.match(chunk, "(%%d+),(%%a+),(%%a+)")
    if ms then
      target = tonumber(ms) + LEAD
      while GetRunningTime() - t0 < target do end
      act(kind, key)
    end
  end
end

function OnEvent(event, arg)
  if event == "MOUSE_BUTTON_PRESSED" and arg == 4 then   -- 侧键上：起弹
    run()
  end
end
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(tpl.replace("__NAME__", name).replace("__DATA__", data).replace("__LEAD__", str(lead)))
    return path


def export_ahk(plan, acts, path, name="三角洲口琴"):
    """AutoHotkey v2 脚本：不依赖 Python，双击即弹（QueryPerformanceCounter 精确定时）。"""
    rows = _flat(plan, acts)
    data = ";".join("%d,%s,%s" % (ms, kind, arg) for ms, kind, arg, _ in rows)
    lead = int(plan[0]['kdn'] * 1000) if plan else 0
    tpl = """; __NAME__ · 自动演奏脚本（由 harmonica/play.py 生成）
; 用法：装 AutoHotkey v2（autohotkey.com，约 3MB）→ 双击本文件 → 切到游戏窗口 → Ctrl+Alt+S 起弹，F10 随时中止
; 提示：本文件是「自带数据 + 忙等定时」的独立脚本，运行期间不需要 Python。
#Requires AutoHotkey v2.0
#SingleInstance Force
SendMode "Input"
SetKeyDelay -1, -1

DATA := "__DATA__"
LEAD := __LEAD__      ; 起弹后第一个音的延时（= 修饰键提前量，倒计时是下面的 Sleep 3000）

QPC() {
    static f := 0, q := 0
    if !f
        DllCall("QueryPerformanceFrequency", "Int64*", &f)
    DllCall("QueryPerformanceCounter", "Int64*", &q)
    return q / f * 1000
}

Act(kind, arg) {
    down := (kind == "kdn" || kind == "mdn")
    if (arg == "left")
        SendEvent down ? "{LButton down}" : "{LButton up}"
    else if (arg == "right")
        SendEvent down ? "{RButton down}" : "{RButton up}"
    else if (arg == "middle")
        SendEvent down ? "{MButton down}" : "{MButton up}"
    else
        SendEvent "{" arg (down ? " down}" : " up}")
}

F10::ExitApp

^!s:: {
    global
    static busy := false
    if busy
        return
    busy := true
    SetTimer () => busy := false, -1000
    ToolTip "3 秒后开始，请切到游戏窗口（F10 中止）"
    Sleep 3000
    ToolTip
    t0 := QPC()
    Loop Parse, DATA, ";" {
        if (A_LoopField == "")
            continue
        p := StrSplit(A_LoopField, ",")
        while (QPC() - t0 < p[1] + LEAD)
            Sleep 1
        Act(p[2], p[3])
    }
}
"""
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(tpl.replace("__NAME__", name).replace("__DATA__", data).replace("__LEAD__", str(lead)))
    return path
