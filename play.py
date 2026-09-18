#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""play.py — 自动弹奏（三角洲行动 口琴玩法）v3

时序模型取自同款游戏的权威实现 MidiKeyPlayer（Engine/InputTiming.cs）：
**游戏是按帧采样输入的（60fps≈16.7ms/帧）**，物理间隔必须给足，不能被节奏缩放：

    档位          帧长   修饰键提前  最短按住  抬起→按下  同键重触发
    标准(60fps)   16.7   40ms       45ms     40ms      45ms
    稳健(30fps)   33.3   70ms       80ms     70ms      80ms
    极限(高帧率)    8     20ms       22ms     18ms      22ms

v2 的两个致命问题：
  1) 每个音只按住 70ms 就松手（staccato），音与音之间是大段静音
     → 听感就是 "ABC 缓一会 DE 缓一会 FG"。
  2) 修饰键（中键=半音 / 右键=升调）只提前 6ms 按下，不足一帧
     → 游戏采样不到 → 音高偶发错，"个别音不准"。
v3：
  * 每个音按住「谱面时值 − 抬起余量」，两音之间只留 ~40ms 气口 → 连贯；
    简谱的增时线 `-`（延长一拍）靠"按住"表现，长音真正拖住。
  * 修饰键按帧预算给足提前量；状态变化时先松旧的后按新的，绝不与音键同帧。
  * 自带时序探针：逐音记录 计划/实际时刻、调度迟到、与上一音的间隔、修饰键提前量、按住时长。
    --debug-timing 打印全部明细并导出 timing_log.csv。

常用：
    python play.py --dry-run                 # 只打印时间轴（不按键）
    python play.py --countdown 8             # 8 秒倒计时后开始（期间切到游戏窗口）
    python play.py --debug-timing            # 演奏 + 逐音延迟报表
    python play.py --timing safe             # 机器卡 / 30fps 用稳健档
    python play.py --from-measure 1 --to-measure 4
    python play.py --calib                   # 用耳朵确认中键/右键/左键的语义
    播放中随时按 F10 立即停止（会松掉所有按键）
"""
import argparse, csv, ctypes, json, os, sys, time
from ctypes import wintypes as wt

user32 = ctypes.WinDLL('user32', use_last_error=True)
winmm = ctypes.WinDLL('winmm')
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# ---------- 输入注入 (SendInput: 键盘 VK/扫描码 + 鼠标按键) ----------
KEYEVENTF_SCANCODE, KEYEVENTF_KEYUP = 0x0008, 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
SCAN = {'Z': 0x2C, 'X': 0x2D, 'C': 0x2E, 'V': 0x2F, 'B': 0x30, 'N': 0x31, 'M': 0x32,
        ',': 0x33, 'F10': 0x44, 'ESC': 0x01}
VK = {'Z': 0x5A, 'X': 0x58, 'C': 0x43, 'V': 0x56, 'B': 0x42, 'N': 0x4E, 'M': 0x4D,
      ',': 0xBC, 'F10': 0x79, 'ESC': 0x1B}
INPUT_MODE = ['vk']        # vk(默认) | scan(DirectInput 型游戏) | both
MOUSE = {'middle': (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
         'right': (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
         'left': (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)}

# ---------- 输入时序预算（物理毫秒，来自 MidiKeyPlayer.Engine.InputTiming） ----------
TIMINGS = {
    'standard':   dict(name='标准(60fps)', frame=16.7, mod_lead=40, min_hold=45, release_gap=40,
                       retrigger=45, lead_ms=57),
    'safe':       dict(name='稳健(30fps/卡顿)', frame=33.3, mod_lead=70, min_hold=80, release_gap=70,
                       retrigger=80, lead_ms=104),
    'aggressive': dict(name='极限(高帧率)', frame=8.0, mod_lead=20, min_hold=22, release_gap=18,
                       retrigger=22, lead_ms=28),
}
MOD_SWITCH_EXTRA = 0.008   # 修饰键状态变化时，前一个音额外让出的时间


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wt.WORD), ('wScan', wt.WORD), ('dwFlags', wt.DWORD),
                ('time', wt.DWORD), ('dwExtraInfo', ctypes.POINTER(wt.ULONG))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wt.LONG), ('dy', wt.LONG), ('mouseData', wt.DWORD),
                ('dwFlags', wt.DWORD), ('time', wt.DWORD),
                ('dwExtraInfo', ctypes.POINTER(wt.ULONG))]


class _U(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wt.DWORD), ('u', _U)]


def _send(inp):
    n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if n != 1:
        print(f"! SendInput 失败 err={ctypes.get_last_error()}", file=sys.stderr)


def _key_event(name, up):
    mode = INPUT_MODE[0]
    flags = KEYEVENTF_KEYUP if up else 0
    if mode in ('scan', 'both'):
        flags |= KEYEVENTF_SCANCODE
    _send(INPUT(type=INPUT_KEYBOARD, u=_U(ki=KEYBDINPUT(VK[name], SCAN[name], flags, 0, None))))
    if mode == 'both':
        f2 = (KEYEVENTF_KEYUP if up else 0) | KEYEVENTF_SCANCODE
        _send(INPUT(type=INPUT_KEYBOARD, u=_U(ki=KEYBDINPUT(0, SCAN[name], f2, 0, None))))


def key_down(name):
    _key_event(name, False)


def key_up(name):
    _key_event(name, True)


def mouse_down(btn):
    _send(INPUT(type=INPUT_MOUSE, u=_U(mi=MOUSEINPUT(0, 0, 0, MOUSE[btn][0], 0, None))))


def mouse_up(btn):
    _send(INPUT(type=INPUT_MOUSE, u=_U(mi=MOUSEINPUT(0, 0, 0, MOUSE[btn][1], 0, None))))


def abort_requested(abort_vk='F10'):
    return bool(user32.GetAsyncKeyState(VK[abort_vk]) & 0x8000)


def boost_priority():
    try:
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x0080)
    except Exception:
        pass
    try:
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 2)
    except Exception:
        pass


def sleep_until(t):
    """睡到绝对时间 t（perf_counter 时钟）。"""
    while True:
        d = t - time.perf_counter()
        if d <= 0:
            return
        if d > 0.0005:
            time.sleep(d - 0.0005)
        else:
            time.sleep(0)


ACTION_ORDER = {'mup': 0, 'kup': 0, 'mdn': 1, 'kdn': 1}    # 同一时刻：先松旧音，再按新音


def build_timeline(score, args):
    """展开成 (音清单, 动作队列, 总时长s)。动作 = (t, kind, arg, 音序号)。"""
    T = TIMINGS[args.timing]
    mod_lead = T['mod_lead'] / 1000.0
    min_hold, rel_gap = T['min_hold'] / 1000.0, T['release_gap'] / 1000.0
    beat = 60.0 / args.bpm
    bpm_m = score['beats_per_measure']
    shift = mod_lead                                    # 第一个音的修饰键也要有提前量
    notes, off = [], 0.0
    # 表中每个小节自带 start_beat（源谱小节线的真实位置）时用它 —— 弱起、末尾短小节、
    # 变拍号的谱面才不会按「每小节固定 4 拍」推算而整体错位；老表没有这个字段就沿用累加。
    src = (not args.pad) and all('start_beat' in m for m in score['measures'])
    for mi, m in enumerate(score['measures'], 1):
        short = m['beats'] < bpm_m - 1e-6 and not m.get('confident', False)
        span = bpm_m if (args.pad and short) else m['beats']
        base = (m['start_beat'] * beat) if src else off
        if args.from_measure <= mi <= args.to_measure:
            for ev in m['events']:
                notes.append(dict(t=shift + base + ev['beat'] * beat, mi=mi, ev=ev,
                                  dur=ev['beats'] * beat))
        off += span * beat
    acts, plan, cur, prev_kup = [], [], set(), None
    for n in notes:
        ev, t, dur = n['ev'], n['t'], n['dur']
        if not ev['key']:
            continue
        need = set(ev['mods'])
        change = need != cur
        hold = max(min_hold, dur - rel_gap - (MOD_SWITCH_EXTRA if change else 0.0))
        hold = min(hold, dur)
        kdn, kup = t, t + hold
        idx = len(plan)
        if change:
            rel_at = (prev_kup + 0.001) if prev_kup is not None else min(kdn, 0.001)
            for m_ in sorted(cur - need):               # 先松掉不再需要的修饰键
                acts.append((rel_at, 'mup', m_, None))
                rel_at += 0.001
            for m_ in sorted(need - cur):               # 再按上需要的（尽量给足提前量）
                at = max(rel_at, kdn - mod_lead)
                acts.append((at, 'mdn', m_, None))
                rel_at = at + 0.001
        acts.append((kdn, 'kdn', ev['key'], idx))
        acts.append((kup, 'kup', ev['key'], idx))
        plan.append(dict(idx=idx, t=t, kdn=kdn, kup=kup, hold=hold, key=ev['key'],
                         mods=sorted(need), mi=n['mi'], beats=ev['beats'],
                         note=ev.get('note'), change=change, dur=dur,
                         compressed=change and hold <= min_hold + 1e-9))
        cur, prev_kup = need, kup
    acts.sort(key=lambda a: (round(a[0], 6), ACTION_ORDER[a[1]]))
    return plan, acts, off


def _apply(kind, arg):
    if kind == 'kdn':
        key_down(arg)
    elif kind == 'kup':
        key_up(arg)
    elif kind == 'mdn':
        mouse_down(arg)
    else:
        mouse_up(arg)


class Probe:
    """时序探针（口径对齐 MidiKeyPlayer.InputTimingProbe）：用**实际发出**的时刻计算。"""

    def __init__(self, T):
        self.T = T
        self.total = self.mod_lead_short = self.mod_lead_zero = self.retrig_short = 0
        self.hold_short = self.compressed = 0
        self.min_mod_lead = float('inf')
        self.late, self.rows = [], []
        self._last_key = self._last_kdn = self._last_kup = self._last_mdn = None
        self._held = 0

    def on_mod(self, kind):
        if kind == 'mdn':
            self._last_mdn = time.perf_counter()
            self._held += 1
        elif kind == 'mup':
            self._held = max(0, self._held - 1)

    def on_note(self, p, t_kdn, t_kup, lag, t0):
        lead = (t_kdn - self._last_mdn) * 1000.0 if (self._held > 0 and self._last_mdn) else None
        gap = (t_kdn - self._last_kup) * 1000.0 if self._last_kup else None
        retrig = (t_kdn - self._last_kdn) * 1000.0 if self._last_key == p['key'] else None
        self.total += 1
        if lead is not None:
            self.min_mod_lead = min(self.min_mod_lead, lead)
            if lead < self.T['frame']:
                self.mod_lead_short += 1
            if lead < 0.5:
                self.mod_lead_zero += 1
        if retrig is not None and retrig < self.T['retrigger']:
            self.retrig_short += 1
        hold_ms = (t_kup - t_kdn) * 1000.0
        if hold_ms < self.T['frame']:
            self.hold_short += 1
        if p['compressed']:
            self.compressed += 1
        self.late.append(lag)
        self.rows.append(dict(idx=self.total, measure=p['mi'], key=p['key'],
                              mods='+'.join(p['mods']), beats=p['beats'],
                              planned_ms=round(p['kdn'] * 1000, 1),
                              actual_ms=round((t_kdn - t0) * 1000, 1),
                              lag_ms=round(lag * 1000, 1),
                              gap_ms=(round(gap, 1) if gap is not None else ''),
                              mod_lead_ms=(round(lead, 1) if lead is not None else ''),
                              hold_ms=round(hold_ms, 1),
                              retrig_ms=(round(retrig, 1) if retrig is not None else '')))
        self._last_key, self._last_kdn, self._last_kup = p['key'], t_kdn, t_kup

    def summary(self, dropped=0):
        T, lat = self.T, self.late
        out = [f"时序诊断（物理毫秒 · 档位 {T['name']}）：音符 {self.total} 个"]
        if lat:
            out.append(f"  调度迟到：平均 {sum(lat)/len(lat)*1000:.1f}ms  最大 {max(lat)*1000:.1f}ms"
                       f"  超过 {T['frame']:.0f}ms 的 {sum(1 for x in lat if x*1000 > T['frame'])} 个")
        lead = '无' if self.min_mod_lead == float('inf') else f"{self.min_mod_lead:.1f}ms"
        out.append(f"  修饰键提前量 <{T['frame']:.1f}ms 的 {self.mod_lead_short} 个（同刻 {self.mod_lead_zero} 个）"
                   f"；最小 {lead}（目标 ≥{T['mod_lead']:.0f}ms）")
        out.append(f"  同键重触发 <{T['retrigger']:.0f}ms 的 {self.retrig_short} 个"
                   f"；按住 <{T['frame']:.1f}ms 的 {self.hold_short} 个"
                   f"；时值被压到下限的 {self.compressed} 个")
        if dropped:
            out.append(f"  （--late drop：为与歌曲对齐丢掉了 {dropped} 个来不及的音，可 --late shift 改为顺延）")
        return "\n".join(out)

    def dump(self, path):
        if not self.rows:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(self.rows[0].keys()))
            w.writeheader()
            w.writerows(self.rows)
        print(f"逐音明细已写入 {path}（planned=计划时刻 actual=实际按下 lag=调度迟到 "
              f"gap=与上一音抬起间隔 mod_lead=修饰键提前量 hold=按住时长，单位 ms）")


SONG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'songs')


def list_songs():
    """列出 songs/ 里现成的曲子（先解析一遍，确保能直接弹）。"""
    import score as sm
    if not os.path.isdir(SONG_DIR):
        print(f"没有 {SONG_DIR} 目录"); return
    files = sorted(f for f in os.listdir(SONG_DIR)
                   if f.lower().endswith(('.jianpu', '.txt', '.mid', '.midi'))
                   and not f.startswith(('_', '.')))
    for f in files:
        p = os.path.join(SONG_DIR, f)
        try:
            s = sm.parse_any(p)
            print(f"  {f:46s} {s.bpm:>5g}BPM  {s.total_beats:>7.1f}拍  "
                  f"{int(s.seconds // 60)}分{s.seconds % 60:04.1f}秒  [{s.fmt}]")
        except Exception as e:
            print(f"  {f:46s} ✗ {type(e).__name__}: {e}")
    print("")
    print("用法：python play.py --song songs/<文件名> --dry-run （换成 --countdown 8 --debug-timing 直接弹）")


def load_song(args):
    """按格式载入谱面 → (事件表, BPM, 描述)。JSON 事件表直接用，其余先解析再换算。"""
    src = args.song or args.score
    if not os.path.exists(src):
        sys.exit(f"找不到谱面文件：{src}")
    if src.lower().endswith('.json'):
        tab = json.load(open(src, encoding='utf-8'))
        return tab, 125.0, f"{os.path.basename(src)}（既有事件表）", None
    import score as sm
    sc = sm.parse_any(src, track=args.midi_track, prefer_name=args.track_name,
                      melody=args.melody, merge=args.merge)
    print(sm.report(sc))
    tab, st = sm.to_score_table(sc, base_octave=args.base_octave, transpose=args.transpose)
    extra = ""
    if args.transpose:
        extra += f" · 整体移调 {args.transpose:+d} 半音"
    print(f"  → 口琴基准八度 {st['base_octave']}（基准音 = 键盘 Z），"
          f"可弹 {st['playable']}/{st['notes']} 个音"
          + (f"，{st['out_of_range']} 个超出口琴音域按休止处理：{' '.join(st['out_notes'][:8])}"
             if st['out_of_range'] else "，全部在音域内") + extra)
    return tab, sc.bpm, f"{os.path.basename(src)}（{sc.fmt} 格式）", sc


def do_export(plan, acts, total, args):
    """导出宏/时间线（照搬 midikey 的 MacroExporter 能力）。"""
    import macros
    stem = os.path.splitext(os.path.basename(args.song or args.score))[0]
    base = args.export_path or f"{stem}_{args.export}"
    ext = {'csv': '.csv', 'timeline': '.txt', 'lua': '.lua', 'ahk': '.ahk'}.get(args.export, '.txt')
    if base.lower().endswith(ext):
        path = base
    else:
        path = base + ext
    if args.export == 'csv':
        macros.export_csv(plan, acts, path)
    elif args.export == 'timeline':
        macros.export_timeline(plan, acts, path)
    elif args.export == 'lua':
        macros.export_lua(plan, acts, path, name=stem)
    elif args.export == 'ahk':
        macros.export_ahk(plan, acts, path, name=stem)
    else:
        sys.exit(f"未知导出格式：{args.export}")
    print(f"已导出 {args.export} 宏：{path}")
    print(f"  含 {len(plan)} 个音 / {len(acts)} 个动作 / 总时长 {total:.2f}s"
          f"（BPM {args.bpm:g}，时序档位 {TIMINGS[args.timing]['name']}）")
    if args.export == 'ahk':
        print("  用法：装 AutoHotkey v2 → 双击该 .ahk → 切到游戏窗口 → Ctrl+Alt+S 起弹，F10 中止")
    elif args.export == 'lua':
        print("  用法：Logitech G HUB → 游戏与应用程序 → 新建 Lua 脚本 → 全量粘贴 → 绑定鼠标侧键")
    elif args.export == 'csv':
        print("  这是逐动作时刻表（毫秒），可用 Excel 打开核对每个音的先后")
    return path


def play(score, args):
    plan, acts, total = build_timeline(score, args)
    T = TIMINGS[args.timing]
    if getattr(args, 'export', ''):          # 兼容只传了部分参数的调用方（如探针脚本）
        return do_export(plan, acts, total, args)
    if args.dry_run:
        print(f"共 {len(plan)} 个音（非休止）/ {len(acts)} 个动作，时长 {total:.2f}s @♩={args.bpm}"
              f"（档位 {T['name']}, pad={'on' if args.pad else 'off'}, 倒计时 {args.countdown}s）")
        last = -1
        for p in plan:
            if p['mi'] != last:
                print(f"--- 第 {p['mi']} 小节 ---")
                last = p['mi']
            print(f"  {p['t']:7.3f}s  {'+'.join(p['mods'] + [p['key']]):22s}"
                  f" 时值 {p['beats']:>4}拍({p['dur']*1000:6.0f}ms) 按住 {p['hold']*1000:4.0f}ms"
                  f" 气口 {(p['dur']-p['hold'])*1000:3.0f}ms")
        return

    print(f"倒计时 {args.countdown}s：请切到游戏窗口并把口琴唤出（播放中按 F10 停止）")
    rem = float(args.countdown)
    while rem > 0:
        print(f"  {rem:g}...", flush=True)
        time.sleep(min(1.0, rem))
        rem -= 1.0
        if abort_requested(args.abort):
            print("已取消")
            return
    print("开始演奏 ♪", flush=True)

    boost_priority()
    probe = Probe(T)
    held, dropped, pending = set(), 0, {}
    base = time.perf_counter() + max(args.lead, T['lead_ms'] / 1000.0)
    probe_base = base
    try:
        for t, kind, arg, nidx in acts:
            target = base + t
            sleep_until(target)
            lag = time.perf_counter() - target
            if abort_requested(args.abort):
                print("\n F10 -> 已停止")
                break
            if lag > args.late_tol and kind == 'kdn':
                if args.late == 'drop':
                    dropped += 1
                    if args.verbose_late:
                        print(f"   丢掉迟到 {lag*1000:5.0f}ms 的音 {arg}", flush=True)
                    continue
                base += lag - args.late_tol * 0.5
                target, lag = time.perf_counter(), 0.0
            if kind in ('mdn', 'mup'):
                probe.on_mod(kind)
            _apply(kind, arg)
            if kind == 'kdn':
                held.add(arg)
                pending[nidx] = (target, lag, probe_base)
            elif kind == 'kup':
                held.discard(arg)
                if nidx in pending:
                    tt, lg, pb = pending.pop(nidx)
                    probe.on_note(plan[nidx], tt, target, lg, pb)
            if kind == 'mup' and arg in ('middle', 'right', 'left'):
                pass
    finally:
        for m in ('left', 'middle', 'right'):
            mouse_up(m)
        for k in list(held) + list(SCAN):
            key_up(k)
    print(probe.summary(dropped))
    if args.debug_timing:
        print("\n逐音明细（planned 计划 / actual 实际 / lag 迟到 / gap 与上一音抬起间隔 / "
              "mod_lead 修饰键提前量 / hold 按住，单位 ms）：")
        for r in probe.rows:
            m = (r['mods'] + '+') if r['mods'] else ''
            print(f"  #{r['idx']:<4d} 小节{r['measure']:<4d} {m+r['key']:<8s} {r['beats']:>5}拍"
                  f" 计划{r['planned_ms']:9.1f} 实际{r['actual_ms']:9.1f} 迟到{r['lag_ms']:6.1f}"
                  f" 间隔{str(r['gap_ms']):>8} 修饰提前{str(r['mod_lead_ms']):>8} 按住{r['hold_ms']:6.1f}")
        probe.dump(args.timing_log or 'timing_log.csv')
    print(f"结束（{time.strftime('%H:%M:%S')}）")


def calib(args):
    """校准：用耳朵确认鼠标三键在游戏里的真实语义（中键=半音? 右键=升八度?）。"""
    T = TIMINGS[args.timing]
    ml, hold, gap = T['mod_lead'] / 1000.0, 0.30, 0.45
    seqs = [
        ("A 中音自然音阶（不按任何鼠标键）", [([], k) for k in ('Z', 'X', 'C', 'V', 'B', 'N', 'M', ',')]),
        ("B 按住【中键】+ 同样音阶（判断是否为升高半音）", [('middle', k) for k in ('Z', 'X', 'C', 'V', 'B', 'N', 'M', ',')]),
        ("C 按住【右键】+ 同样音阶（判断是否为升高八度）", [('right', k) for k in ('Z', 'X', 'C', 'V', 'B', 'N', 'M', ',')]),
        ("D 按住【左键】+ 同样音阶（判断是否为降低八度）", [('left', k) for k in ('Z', 'X', 'C', 'V', 'B', 'N', 'M', ',')]),
        ("E 按住【中键+右键】+ V（高音 #4）", [(['middle', 'right'], 'V')]),
        ("F 只按 V，按住 1 秒（判断长按是否会拖音）", [([], 'V')]),
    ]
    print(f"校准：共 6 组，倒计时 {args.countdown}s 后开始（每组先用文字报出题目）")
    rem = float(args.countdown)
    while rem > 0:
        print(f"  {rem:g}...", flush=True)
        time.sleep(min(1.0, rem))
        rem -= 1.0
    for title, seq in seqs:
        print(title, flush=True)
        for mods, k in seq:
            for m in mods:
                mouse_down(m)
            if mods:
                time.sleep(ml)
            key_down(k)
            time.sleep(1.0 if '按住 1 秒' in title else hold)
            key_up(k)
            for m in reversed(mods):
                mouse_up(m)
            time.sleep(gap)
        time.sleep(0.7)
    print("校准结束")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--score', default='score2.json', help='既有的 JSON 事件表')
    ap.add_argument('--song', default='', help='任意格式谱面：.json 事件表 / .mid / 简谱 .txt/.jianpu')
    ap.add_argument('--list-songs', action='store_true', help='列出 songs/ 里现成的曲子')
    ap.add_argument('--transpose', type=int, default=0, help='整体移调多少半音（默认 0）')
    ap.add_argument('--base-octave', default='auto', help="口琴基准八度 auto|2|3|4|5（默认 auto 自动贴合音域）")
    ap.add_argument('--melody', choices=['highest', 'lowest'], default='highest',
                    help='MIDI 和弦时保留最高音(旋律,默认)还是最低音')
    ap.add_argument('--midi-track', type=int, default=None, help='MIDI 指定轨（从 1 数；默认自动挑旋律轨）')
    ap.add_argument('--track-name', default=None, help='MIDI 按音轨名挑（如 主旋律）')
    ap.add_argument('--merge', action='store_true', help='MIDI 把所有非打击乐轨合并演奏')
    ap.add_argument('--export', choices=['', 'ahk', 'lua', 'csv', 'timeline', 'jianpu', 'json'],
                    default='', help='导出宏/时间线后退出：ahk(AutoHotkey) lua(GHUB) csv timeline jianpu json')
    ap.add_argument('--export-path', default='', help='导出文件名（默认 曲名_格式.扩展名）')
    ap.add_argument('--bpm', type=float, default=0, help='速度；0 = 用谱面自带（JSON 事件表回退 125）')
    ap.add_argument('--countdown', type=float, default=6)
    ap.add_argument('--lead', type=float, default=0.0, help='开演前额外留出的秒数')
    ap.add_argument('--timing', choices=list(TIMINGS), default='standard',
                    help='输入时序档位：standard(60fps,默认) / safe(30fps/卡顿) / aggressive(高帧率)')
    ap.add_argument('--mode', choices=['hold', 'tap', 'once'], default='hold', help='（保留兼容，默认 hold）')
    ap.add_argument('--pad', action='store_true', default=False, help='把每小节补齐到拍号（默认关）')
    ap.add_argument('--no-pad', dest='pad', action='store_false')
    ap.add_argument('--from-measure', type=int, default=1)
    ap.add_argument('--to-measure', type=int, default=10 ** 9)
    ap.add_argument('--late', choices=['drop', 'shift'], default='drop',
                    help='迟到处置：drop=丢掉迟到的音(默认) / shift=整条时间轴顺延')
    ap.add_argument('--late-tol', type=float, default=0.05, help='允许的迟到秒数(默认0.05)')
    ap.add_argument('--verbose-late', action='store_true')
    ap.add_argument('--debug-timing', action='store_true', help='打印逐音延迟明细并导出 CSV')
    ap.add_argument('--timing-log', default='', help='CSV 路径（默认 timing_log.csv）')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--calib', action='store_true')
    ap.add_argument('--abort', default='F10')
    ap.add_argument('--input', choices=['vk', 'scan', 'both'], default='vk',
                    help='键盘注入：vk(默认) / scan(DirectInput 型游戏) / both')
    args = ap.parse_args()
    INPUT_MODE[0] = args.input
    try:
        winmm.timeBeginPeriod(1)
    except Exception:
        pass
    if args.calib:
        return calib(args)
    if args.list_songs:
        return list_songs()
    score, bpm, desc, sc = load_song(args)
    args.bpm = args.bpm or bpm or 125.0
    args.bpm = float(args.bpm)
    print(f"谱面：{desc} · BPM {args.bpm:g} · {len(score['measures'])} 小节 · "
          f"时序档位 {TIMINGS[args.timing]['name']}")
    if args.export in ('jianpu',):
        import score as sm
        if sc is None:                      # 图片解析出来的事件表：逆向还原成简谱
            sc = sm.from_score_table(score)
        stem = os.path.splitext(os.path.basename(args.song or args.score))[0]
        path = args.export_path or f"{stem}_导出.jianpu"
        if not path.lower().endswith('.jianpu'):
            path += '.jianpu'
        open(path, 'w', encoding='utf-8').write(sm.format_jianpu(sc))
        print(f"已导出简谱：{path}（可直接粘贴到 jiko-official.top/delta 的简谱模式）")
        return path
    if args.export == 'json' and sc is not None:
        stem = os.path.splitext(os.path.basename(args.song or args.score))[0]
        path = args.export_path or f"{stem}_事件表.json"
        if not path.lower().endswith('.json'):
            path += '.json'
        json.dump(score, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f"已导出事件表：{path}（可直接用 play.py --score 载入）")
        return path
    return play(score, args)


if __name__ == '__main__':
    main()
