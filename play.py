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
    python play.py                           # 交互式：提示输入谱面路径 → 回车即开始演奏
                                             #   输入 1        = 按歌名从 jiko 曲库搜索并下载
                                             #   输入文件可直接拖进窗口，带引号也认
    python play.py --dry-run                 # 只打印时间轴（不按键）
    python play.py --song songs/天空之城.jianpu --countdown 8
    python play.py --jiko-search 天空之城       # 非交互：搜歌名下载后直接弹
    python play.py --list-songs               # 列出 songs/ 里现成的曲子
    python play.py --debug-timing            # 演奏 + 逐音延迟报表
    python play.py --timing safe             # 机器卡 / 30fps 用稳健档
    python play.py --from-measure 1 --to-measure 4
    python play.py --calib                   # 用耳朵确认中键/右键/左键的语义
    播放中随时按 F10 立即停止（会松掉所有按键）
"""
import argparse, csv, ctypes, json, os, re, sys, time
from ctypes import wintypes as wt

import harmonica_config as hcfg

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
# 同一个键必须「抬起来再按下去」，游戏才认第二下。上游 60fps 档给的是 松→按 ≥40ms
# （按 60Hz 采样 2.4 帧算）。这个下限**不随显示帧率放宽**：游戏内部的输入采样未必跟着
# 显示器刷新率走，压到 18~26ms 时第二下会被吞掉（暗号开头连击 riff 实测缺音、听不出来）。
RETRIG_MIN_MS = 40.0
TIMINGS = {
    'standard':   dict(name='标准(60fps)', frame=16.7, mod_lead=40, min_hold=45, release_gap=40,
                       retrigger=45, lead_ms=57),
    'safe':       dict(name='稳健(30fps/卡顿)', frame=33.3, mod_lead=70, min_hold=80, release_gap=70,
                       retrigger=80, lead_ms=104),
    'aggressive': dict(name='极限(高帧率)', frame=8.0, mod_lead=20, min_hold=22, release_gap=18,
                       retrigger=40, lead_ms=28),
}
MOD_SWITCH_EXTRA = 0.008   # 修饰键状态变化时，前一个音额外让出的时间


def timing_of(args):
    """实际使用的时序档位。

    显式给了 --timing（standard / safe / aggressive）就**强制**用内置档位 —— 那是「更保守」
    的逃生门：某台机器 40ms 还不够时，直接 --timing safe 上 80ms。
    没给则按本机帧率自适应（harmonica_config 首次运行问一次并记住），比例由上游
    InputTiming 三档反推：「帧长 × 2.4 / 2.7 / 2.4」+ 下限，60Hz 时精确等于内置 standard。
    """
    forced = getattr(args, 'timing', None)
    T = dict(TIMINGS[forced or 'standard'])
    fps = getattr(args, '_fps', None)
    if fps and not forced:
        p = hcfg.profile_for(fps)
        T.update(frame=p['frame'], mod_lead=p['mod_lead'], min_hold=p['min_hold'],
                 release_gap=p['release_gap'], retrigger=max(p['min_hold'], RETRIG_MIN_MS),
                 lead_ms=p['lead_ms'], name=f"{T['name'].split('(')[0]}({p['name']})")
    return T


def retrigger_of(args) -> float:
    """同一个键「抬→按」的最短间隔（毫秒）。

    默认取档位值，但不低于 RETRIG_MIN_MS；--retrigger-ms 可手工指定（允许更小，仅供调试）。
    """
    val = float(getattr(args, 'retrigger_ms', 0.0) or 0.0)
    if val > 0:
        return val
    return max(float(timing_of(args)['retrigger']), RETRIG_MIN_MS)


def ensure_fps(args):
    """拿到本机帧率，并把结果记进 ~/.harmonica_config.json。

    优先级：--fps 命令行 > 已存的配置 > 首次运行问一次 > 无交互则用内置 60fps 档。
    只问一次；之后想改：--fps 165 或 --reconfig。
    """
    if args.fps:
        cfg = hcfg.load()
        cfg['fps'] = float(args.fps)
        hcfg.save(cfg)
        return float(args.fps)
    cfg = hcfg.load()
    if cfg.get('fps') and not args.reconfig:
        return float(cfg['fps'])
    # 非交互（管道/脚本里跑）就别卡住，直接用内置档；也不写配置，留给下次真人运行再问
    if not (args.reconfig or args.interactive or sys.stdin.isatty()):
        return None
    det = hcfg.detect_refresh_rate()
    print('─' * 62)
    print('  第一次运行：时序档位要按你的帧率来配（只问这一次，之后自动记住）')
    print('  目标程序按帧采样输入，「修饰键提前量 / 最短按住」都是帧长的倍数，')
    print('  所以帧率直接决定预算：165Hz 用 20ms 就够，30Hz 得给到 80ms。')
    if det:
        print(f'  自动检测到显示器刷新率：{det} Hz（游戏内帧率不同就填实际值）')
    try:
        s = input(f'  帧率 [{"auto:" + str(det) if det else "60"}] > ').strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    fps = float(det or hcfg.DEFAULT_FPS)
    if s:
        got = re.sub(r'[^\d.]', '', clean_input_path(s))
        try:
            if got:
                fps = float(got)
        except Exception:
            print(f'  没看懂「{s}」，先用 {fps:g}Hz')
    fps = max(10.0, min(1000.0, fps))
    cfg['fps'] = fps
    ok = hcfg.save(cfg)
    p = hcfg.profile_for(fps)
    print(f'  已记住 {fps:g}Hz → 帧长 {p["frame"]}ms · 修饰键提前 {p["mod_lead"]}ms · '
          f'最短按住 {p["min_hold"]}ms · 抬-按间隔 {p["release_gap"]}ms')
    print(f'  （存在 {hcfg.CONFIG_PATH if ok else "内存里（写文件失败）"}；改：--fps 165 / --reconfig）')
    print('─' * 62)
    return fps


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
    T = timing_of(args)
    mod_lead = T['mod_lead'] / 1000.0
    min_hold, rel_gap = T['min_hold'] / 1000.0, T['release_gap'] / 1000.0
    re_trig = retrigger_of(args) / 1000.0       # 同一个键「抬→按」的最短间隔
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
    # 第一遍：按理想时刻排开（时值里留出 release_gap 当气口）
    plan, prev_mods = [], None
    for n in notes:
        ev, t, dur = n['ev'], n['t'], n['dur']
        if not ev['key']:
            continue
        need = set(ev['mods'])
        change = need != prev_mods
        hold = max(min_hold, dur - rel_gap - (MOD_SWITCH_EXTRA if change else 0.0))
        hold = min(hold, dur)
        plan.append(dict(idx=len(plan), t=t, kdn=t, kup=t + hold, hold=hold, key=ev['key'],
                         mods=sorted(need), mi=n['mi'], beats=ev['beats'], note=ev.get('note'),
                         change=change, dur=dur, compressed=False, fix='', silent=False))
        prev_mods = need

    # 第二遍：同一个键必须真的「抬起来再按下去」，否则游戏只认第一下（缺音）。
    # 间隔不够就先把这一下往后挪到满足间距（晚十几毫秒，但听得见）；实在挪不进去（音太短）
    # 就并进前一个同键音，用一个长音顶过去 —— 宁可连成一片，也绝不能缺音。
    last = {}
    for p in plan:
        i = last.get(p['key'])
        if i is not None:
            prev = plan[i]
            want = prev['kup'] + re_trig
            if p['kdn'] < want:
                end = p['t'] + p['dur']
                # 往后挪不能挤掉「下一个音」的抬起余量（前音抬→后音按 ≥release_gap）：
                # 上限取「自己的时值末尾」和「下一个音的按下时刻 - 抬起余量」里更紧的那个。
                nxt = plan[p['idx'] + 1] if p['idx'] + 1 < len(plan) else None
                room = min(end, (nxt['kdn'] - rel_gap) if nxt else end)
                if want + min_hold <= room:                      # 塞得下 → 往后挪
                    p['kdn'] = want
                    p['kup'] = min(max(want + min_hold, want + p['hold']), room)
                    p['hold'] = p['kup'] - p['kdn']
                    p['fix'] = 'pushed'
                else:                                           # 塞不下 → 并进前一个同键音
                    prev['kup'] = max(prev['kup'], end)
                    prev['hold'] = prev['kup'] - prev['kdn']
                    p['silent'] = True
                    p['fix'] = 'merged'
                    continue
        last[p['key']] = p['idx']

    # 第三遍：展开成动作。修饰键状态按**实际发出**的音序推演，并进/挪后都不会错位。
    acts, cur, prev_kup = [], set(), None
    for p in plan:
        if p.get('silent'):
            continue
        need = set(p['mods'])
        p['change'] = need != cur
        if p['change']:
            rel_at = (prev_kup + 0.001) if prev_kup is not None else min(p['kdn'], 0.001)
            for m_ in sorted(cur - need):                   # 先松掉不再需要的修饰键
                acts.append((rel_at, 'mup', m_, None))
                rel_at += 0.001
            for m_ in sorted(need - cur):                   # 再按上需要的（尽量给足提前量）
                at = max(rel_at, p['kdn'] - mod_lead)
                acts.append((at, 'mdn', m_, None))
                rel_at = at + 0.001
        acts.append((p['kdn'], 'kdn', p['key'], p['idx']))
        acts.append((p['kup'], 'kup', p['key'], p['idx']))
        p['compressed'] = p['change'] and p['hold'] <= min_hold + 1e-9
        cur, prev_kup = need, p['kup']
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
        self._up = {}                                  # key -> 上一次抬起的时刻
        self.retrig_pushed = self.retrig_merged = 0

    def on_mod(self, kind):
        if kind == 'mdn':
            self._last_mdn = time.perf_counter()
            self._held += 1
        elif kind == 'mup':
            self._held = max(0, self._held - 1)

    def on_note(self, p, t_kdn, t_kup, lag, t0):
        lead = (t_kdn - self._last_mdn) * 1000.0 if (self._held > 0 and self._last_mdn) else None
        gap = (t_kdn - self._last_kup) * 1000.0 if self._last_kup else None
        # 同键重触发 = 上一次**这个键**抬起的时刻 → 这次按下。若用「按下→按下」，按住的那段
        # 时间会被算进去（26ms 的真实间隔报成 250ms），这类缺音就永远查不出来。
        prev_up = self._up.get(p['key'])
        retrig = (t_kdn - prev_up) * 1000.0 if prev_up is not None else None
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
        self._up[p['key']] = t_kup

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
        if self.retrig_pushed or self.retrig_merged:
            out.append(f"  同键连击修正：挪后 {self.retrig_pushed} 个 / 并成长音 {self.retrig_merged} 个"
                       f"（同一个键要让游戏看得到抬起，间隔 ≥{T['retrigger']:.0f}ms）")
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


ROOT = os.path.dirname(os.path.abspath(__file__))
SONG_DIR = os.path.join(ROOT, 'songs')


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
    if args.min_rest > 0:                      # 抹平过短的休止（可选听感修正，默认关）
        fixed = sm.squeeze_short_rests(sc, args.min_rest)
        if fixed:
            print(f"  · 已抹平 {fixed} 处 ≤{args.min_rest:g} 拍的短休止"
                  f"（--min-rest 0 可还原谱面原样）")
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
          f"（BPM {args.bpm:g}，时序档位 {timing_of(args)['name']}）")
    if args.export == 'ahk':
        print("  用法：装 AutoHotkey v2 → 双击该 .ahk → 切到游戏窗口 → Ctrl+Alt+S 起弹，F10 中止")
    elif args.export == 'lua':
        print("  用法：Logitech G HUB → 游戏与应用程序 → 新建 Lua 脚本 → 全量粘贴 → 绑定鼠标侧键")
    elif args.export == 'csv':
        print("  这是逐动作时刻表（毫秒），可用 Excel 打开核对每个音的先后")
    return path


def play(score, args):
    plan, acts, total = build_timeline(score, args)
    T = timing_of(args)
    n_push = sum(1 for p in plan if p['fix'] == 'pushed')
    n_merge = sum(1 for p in plan if p['fix'] == 'merged')
    if getattr(args, 'export', ''):          # 兼容只传了部分参数的调用方（如探针脚本）
        return do_export(plan, acts, total, args)
    if args.dry_run:
        print(f"共 {len(plan)} 个音（非休止）/ {len(acts)} 个动作，时长 {total:.2f}s @♩={args.bpm}"
              f"（档位 {T['name']}, pad={'on' if args.pad else 'off'}, 倒计时 {args.countdown}s）")
        if n_push or n_merge:
            print(f"  同键连击修正：挪后 {n_push} 个 / 并成长音 {n_merge} 个"
                  f"（同一个键要让游戏看得到抬起，间隔 ≥{retrigger_of(args):.0f}ms）")
        last = -1
        for p in plan:
            if p['silent']:
                continue
            if p['mi'] != last:
                print(f"--- 第 {p['mi']} 小节 ---")
                last = p['mi']
            print(f"  {p['t']:7.3f}s  {'+'.join(p['mods'] + [p['key']]):22s}"
                  f" 时值 {p['beats']:>4}拍({p['dur']*1000:6.0f}ms) 按住 {p['hold']*1000:4.0f}ms"
                  f" 气口 {(p['dur']-p['hold'])*1000:3.0f}ms"
                  f"{' ←同键挪后' if p['fix'] == 'pushed' else ''}")
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
    probe.retrig_pushed, probe.retrig_merged = n_push, n_merge
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
    T = timing_of(args)
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


# ───────────────────────── 交互式选曲（直接跑 python play.py） ─────────────────────────

QUOTE_PAIRS = [('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’'), ('「', '」'), ('『', '』')]


def clean_input_path(s):
    """清掉用户粘进来的输入里的包装：包裹引号（拖拽/「复制为路径」都会带）、零宽字符、首尾空白。

    支持 ""…""、''…''、中文引号 “”‘’「」『』，可嵌套多层（复制两次就套两层）。
    """
    s = str(s or '').replace('\u200b', '').replace('\ufeff', '').replace('\xa0', ' ').strip()
    changed = True
    while changed and len(s) > 2:
        changed = False
        for a, b in QUOTE_PAIRS:
            if s.startswith(a) and s.endswith(b):
                s = s[len(a):-len(b)].strip()
                changed = True
    return s


def win_path(p):
    """把 Git-Bash/MSYS 风格路径（/f/TUVSUD/…）与 ~ 转成 Windows Python 认识的路径。"""
    p = os.path.expanduser(str(p or '').strip())
    if re.match(r'^/[A-Za-z](?:/|$)', p):
        p = p[1].upper() + ':' + p[2:]
    if re.match(r'^[A-Za-z]:', p) or p.startswith(('\\\\', '//')):
        return os.path.normpath(p)
    return os.path.normpath(os.path.abspath(p))


def find_local(key):
    """在 songs/ 里按名字找 → [(文件名, 完整路径), …]，精确命中排最前。"""
    if not os.path.isdir(SONG_DIR):
        return []
    files = sorted(f for f in os.listdir(SONG_DIR)
                   if f.lower().endswith(('.jianpu', '.txt', '.mid', '.midi'))
                   and not f.startswith(('_', '.')))
    norm = lambda x: re.sub(r'[\s_\-（）()【】\[\]·]+', '', str(x)).lower()
    key = str(key or '').strip()
    stem = os.path.splitext(key)[0]
    exact, fuzzy = [], []
    for f in files:
        fstem = os.path.splitext(f)[0]
        if f == key or fstem == key or f.lower() == key.lower() or fstem.lower() == stem.lower():
            exact.append(f)
        elif norm(key) and norm(key) in norm(fstem):
            fuzzy.append(f)
    out = list(dict.fromkeys(exact + fuzzy))
    return [(f, os.path.join(SONG_DIR, f)) for f in out]


def resolve_song_input(raw):
    """把一行输入解析成实际谱面路径 → (路径 or None, 失败原因)。"""
    s = clean_input_path(raw)
    if not s:
        return None, '空输入'
    base = win_path(s)
    cands = [base]
    if not os.path.splitext(base)[1]:
        cands += [base + e for e in ('.jianpu', '.txt', '.mid', '.midi', '.json')]
    else:
        root, ext = os.path.splitext(base)
        if ext.lower() == '.midi':
            cands.append(root + '.mid')
        elif ext.lower() == '.mid':
            cands.append(root + '.midi')
    for c in cands:
        if os.path.isfile(c):
            return c, ''
    if os.path.isdir(base):
        return None, f'「{base}」是个文件夹，需要指到具体谱面文件'
    return None, f'找不到文件：{base}'


def print_banner():
    print('=' * 66)
    print('  三角洲行动 · 口琴自动弹奏')
    print('-' * 66)
    print('  把谱面文件直接拖进本窗口，或粘贴路径（带引号也认）')
    print('  输入 1        → 按歌名从 jiko 曲库搜索并下载到 songs/')
    print('  输入 ?        → 列出 songs/ 里现成的曲子')
    print('  输入 q        → 退出')
    print('=' * 66)


def download_by_name(args, name=None):
    """按歌名从 jiko 曲库搜索 + 下载到 songs/ → 返回落盘路径（失败 None）。

    name=None 时会就地提示输入歌名（交互模式）；给了歌名则完全不发问（--jiko-search 用）。
    """
    try:
        import jiko_lib
    except Exception as e:
        print(f"  ✗ 曲库模块加载失败：{type(e).__name__}: {e}")
        return None
    if name is None:
        try:
            name = input('歌名（直接回车取消）> ')
        except (EOFError, KeyboardInterrupt):
            print()
            return None
    name = clean_input_path(name)
    if not name:
        return None
    try:
        songs, src = jiko_lib.load_songs(force=args.refresh_lib)
    except Exception as e:
        print(f"  ✗ 取不到曲库：{e}")
        print(f"    可手动打开 {jiko_lib.BASE} 的「曲库」核对，或在有网时重试")
        return None
    hits = jiko_lib.search(name, songs, limit=10)
    if not hits:
        print(f"  ✗ 曲库里没有「{name}」（曲库共 {len(songs)} 首）")
        for s in jiko_lib.suggest(name, songs):
            print(f"     你是想找：{jiko_lib.describe(s)} ？（python play.py --jiko-search 关键词）")
        return None
    top = hits[0]
    # 只有「第一名的优势不明显」时才让人选，避免每次都多问一句
    if len(hits) > 1 and top[0] < 1000 and top[0] - hits[1][0] < 250:
        print(f"  曲库里匹配到 {len(hits)} 条，选一个：")
        for i, (sc, s) in enumerate(hits, 1):
            print(f"    {i:2d}. [{sc:4d}] {jiko_lib.describe(s)}")
        try:
            pick = input('  编号（回车=第 1 个，c=取消）> ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if pick.lower() in ('c', 'cancel', '取消'):
            return None
        if pick.isdigit() and 1 <= int(pick) <= len(hits):
            top = hits[int(pick) - 1]
        elif pick:
            print('  没听懂，按第 1 个处理')
    song = top[1]
    print(f"  选中：{jiko_lib.describe(song)}（匹配度 {top[0]}）")
    path, note = jiko_lib.download(song, out_dir=SONG_DIR, overwrite=args.force)
    print(f"  已放进曲谱文件夹：{path}")
    return path


def interactive_pick(args, pending=None):
    """交互选曲：返回选定的谱面路径；None = 用户退出。pending 用于「再来一首」直接复用那行输入。"""
    if pending is None:
        print_banner()
    while True:
        if pending is None:
            try:
                raw = input('谱面 > ')
            except (EOFError, KeyboardInterrupt):
                print()
                return None
        else:
            raw = pending
            pending = None
        s = clean_input_path(raw)
        low = s.lower()
        if low in ('q', 'quit', 'exit', ':q', '退出', '结束'):
            print('已退出。')
            return None
        # 1（或 “1 歌名”）→ 在线搜索下载
        if s in ('1', '１') or low in ('search', 'download', 'dl', 'jiko', '搜索', '下载'):
            got = download_by_name(args, None)
            if got:
                return got
            continue
        m = re.match(r'^[1１][\s\u3000]+(.+)$', s)
        if m and not os.path.exists(win_path(m.group(1).strip())):
            got = download_by_name(args, m.group(1).strip())
            if got:
                return got
            continue
        if not s or low in ('?', 'ls', 'list', '列表', 'help'):
            list_songs()
            continue
        path, why = resolve_song_input(s)
        if path:
            return path
        hits = find_local(os.path.splitext(s)[0] if os.path.splitext(s)[1] else s)
        if len(hits) == 1:
            print(f"  按名字匹配到本地曲目：{hits[0][0]}")
            return hits[0][1]
        if hits:
            print(f"  songs/ 里有 {len(hits)} 首名字相近的，选一个：")
            for i, (name, _) in enumerate(hits[:12], 1):
                print(f"    {i:2d}. {name}")
            try:
                pick = input('  编号（回车=取消）> ').strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            if pick.isdigit() and 1 <= int(pick) <= len(hits[:12]):
                return hits[int(pick) - 1][1]
            continue
        print(f"  ✗ {why}")
        print("     提示：文件可以直接拖进本窗口；只记得歌名就输入 1 去曲库搜")


def run_song(args):
    """载入 → 导出 / 演奏。返回 main() 原来的返回值。"""
    score, bpm, desc, sc = load_song(args)
    args.bpm = args.bpm or bpm or 125.0
    args.bpm = float(args.bpm)
    print(f"谱面：{desc} · BPM {args.bpm:g} · {len(score['measures'])} 小节 · "
          f"时序档位 {timing_of(args)['name']}")
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


def interactive_loop(args):
    """交互主循环：选曲 → 演奏 → 问要不要再来一首（直接回车就退出）。"""
    bpm_opt, pending, rc = args.bpm, None, None
    while True:
        path = interactive_pick(args, pending)
        pending = None
        if path is None:
            return rc
        args.song, args.score, args.bpm = path, None, bpm_opt
        try:
            rc = run_song(args)
        except SystemExit as e:                      # load_song 里 sys.exit("找不到谱面")
            print(f"  ✗ {e}")
        except KeyboardInterrupt:
            print('\n已中断。')
        except Exception as e:
            print(f"  ✗ {type(e).__name__}: {e}")
        try:
            nxt = input('\n再来一首？（直接回车退出 / 输入 1 或路径继续）> ')
        except (EOFError, KeyboardInterrupt):
            print()
            return rc
        if not clean_input_path(nxt):
            print('结束。')
            return rc
        pending = nxt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--score', default=None, help='既有的 JSON 事件表（不给谱面时默认 data/score2.json）')
    ap.add_argument('--song', default='', help='任意格式谱面：.json 事件表 / .mid / 简谱 .txt/.jianpu')
    ap.add_argument('-i', '--interactive', action='store_true',
                    help='交互式选曲：提示输入谱面路径（输入 1 = 按歌名从 jiko 曲库下载）'
                         '；不给谱面且终端可交互时自动进入')
    ap.add_argument('--jiko-search', default='', metavar='歌名',
                    help='非交互：直接按歌名从 jiko 曲库搜索并下载到 songs/，然后弹它')
    ap.add_argument('--force', action='store_true', help='下载曲库谱面时覆盖 songs/ 里的同名文件')
    ap.add_argument('--refresh-lib', action='store_true', help='下载前忽略本地缓存，重新拉 jiko 曲库')
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
    ap.add_argument('--timing', choices=list(TIMINGS), default=None,
                    help='强制内置时序档位（更保守的逃生门）：standard(60fps) / safe(30fps/卡顿) / '
                         'aggressive(高帧率)；不给就按本机帧率自适应')
    ap.add_argument('--mode', choices=['hold', 'tap', 'once'], default='hold', help='（保留兼容，默认 hold）')
    ap.add_argument('--pad', action='store_true', default=False, help='把每小节补齐到拍号（默认关）')
    ap.add_argument('--no-pad', dest='pad', action='store_false')
    ap.add_argument('--min-rest', type=float, default=0.0, metavar='拍',
                    help='抹平短于该拍数的休止（0.25=只抹 0__，0.5=抹 0__/0_）；默认 0 保留谱面原样')
    ap.add_argument('--from-measure', type=int, default=1)
    ap.add_argument('--to-measure', type=int, default=10 ** 9)
    ap.add_argument('--late', choices=['drop', 'shift'], default='shift',
                    help='迟到处置：shift=整条时间轴顺延(默认，保证不缺音，宁可晚十几毫秒) / '
                         'drop=直接丢掉迟到的音（会让旋律缺音，除非你就是要严格对齐）')
    ap.add_argument('--late-tol', type=float, default=0.05, help='允许的迟到秒数(默认0.05)')
    ap.add_argument('--verbose-late', action='store_true')
    ap.add_argument('--debug-timing', action='store_true', help='打印逐音延迟明细并导出 CSV')
    ap.add_argument('--timing-log', default='', help='CSV 路径（默认 timing_log.csv）')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--calib', action='store_true')
    ap.add_argument('--abort', default='F10')
    ap.add_argument('--input', choices=['vk', 'scan', 'both'], default='vk',
                    help='键盘注入：vk(默认) / scan(DirectInput 型游戏) / both')
    ap.add_argument('--fps', type=float, default=0.0,
                    help='本机帧率/刷新率：配过就按帧率自适应算时序预算（会记住，只配一次）')
    ap.add_argument('--reconfig', action='store_true', help='重新问一次帧率并覆盖本机配置')
    ap.add_argument('--retrigger-ms', type=float, default=0.0, metavar='毫秒',
                    help='同一个键「抬→按」的最短间隔毫秒数；默认取档位值且不低于 40'
                         '（上游 60fps 档权威值，低于它连击的第二下会被游戏吞掉）')
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
    args._fps = ensure_fps(args)            # 首次运行问一次帧率，之后读配置
    if args.jiko_search:                        # 非交互：搜歌名 → 下载 → 直接接着弹
        path = download_by_name(args, args.jiko_search)
        if not path:
            return 1
        args.song = path
    if not args.song and not args.score:
        # 没指定谱面：交互式终端里直接进选曲提示；管道/脚本里保持老行为（data/score2.json），不阻塞
        if args.interactive or sys.stdin.isatty():
            return interactive_loop(args)
        args.score = os.path.join(ROOT, 'data', 'score2.json')
    return run_song(args)


if __name__ == '__main__':
    main()
