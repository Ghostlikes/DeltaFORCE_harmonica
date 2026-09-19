#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一谱面模型 + 多格式读写（照搬三份参考实现的谱面语法）。

内部一律先化成 [(音高, 起始拍, 时值拍)]（音高 = MIDI 音高号，None = 休止），
再用 keymap.map_pitch() 换成游戏按键 —— 与 midikey-player 的
「MidiLoader → NoteMapper → PlaybackEngine」结构一致。

支持的输入格式（自动判别）：
  1. 简谱 DSL   —— jiko-official.top/delta「简谱模式/精确模式」语法
                   1 2 3 4 5 6 7 0 | #4 b7 | 5_ 5__ 5. 5.. 5- 5-- 5:1.25 | 1' ,1 | 5~ 5 | ||: :||
                   变调前缀 L/M/R（L=左键降调、M=中键半音、R=右键升调，可写 LM4 / RM5）
  2. viz2 简谱  —— ChiZhou6/harmonica-visualizer 的 TITLE=/BPM= 头 + 前缀 <b # ^> + 1..7/8
  3. DFH tab    —— Dr-hydra/Delta-Force-Harmonica 的「简谱/键位/节奏」三行小节谱
  4. MIDI       —— .mid/.midi（见 midi_in.py）
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import keymap

BEAT_DEFAULT_BPM = 90.0
# 时值后缀 → 拍数（与 jiko 站点语法一致）
UNDER = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}      # 减时线：每条再砍一半
DOT = {0: 1.0, 1: 1.5, 2: 1.75}                  # 附点：一拍 / 一拍半 / 一拍七五


@dataclass
class Note:
    pitch: int | None      # MIDI 音高号；None = 休止
    start: float           # 起始拍（从曲首算）
    dur: float             # 时值（拍）
    tie: bool = False      # 与后一个同音相连（连音线）
    text: str = ""         # 原始记号（排错用）
    measure: int = 0       # 所在小节（1 起；0=解析器未提供，按网格推算）


@dataclass
class Score:
    title: str
    bpm: float
    meter: str = "4/4"
    key: str = "1=C"
    notes: list = field(default_factory=list)
    source: str = ""
    fmt: str = ""
    warnings: list = field(default_factory=list)

    @property
    def total_beats(self) -> float:
        return max((n.start + n.dur for n in self.notes), default=0.0)

    @property
    def beat_sec(self) -> float:
        return 60.0 / (self.bpm or BEAT_DEFAULT_BPM)

    @property
    def seconds(self) -> float:
        return self.total_beats * self.beat_sec

    def beats_per_measure(self) -> float:
        m = re.match(r"\s*(\d+)\s*/\s*(\d+)", self.meter or "4/4")
        if not m:
            return 4.0
        return int(m.group(1)) * 4.0 / int(m.group(2))


# ================================================================ 简谱 DSL
_TOKEN = re.compile(r"""
    ^(?P<prefix>[LMR]{0,2})
    (?P<acc>[#♯b♭])?
    (?P<low>,{0,2})
    (?P<deg>[0-7])
    (?P<high>'{0,2})
    (?P<dur>[_.\-]{1,8}|[:/]\d+(?:\.\d+)?)?
    (?P<tie>~?)$$
""", re.X)


def _dur_of(spec: str | None, warn, tok) -> float:
    if not spec:
        return 1.0
    if spec[0] in ":/":
        try:
            return float(spec[1:])
        except ValueError:
            warn(f"精确拍数写法不合法：{tok}")
            return 1.0
    u, d, dash = spec.count("_"), spec.count("."), spec.count("-")
    if u > 3:
        warn(f"减时线超过三条：{tok}")
    if d > 2:
        warn(f"附点超过两个：{tok}")
    # 减时线折半 × 附点放大 + 每根延长线加一拍：_. = 0.75 拍，_- = 1.5 拍，-- = 3 拍
    return UNDER[min(u, 3)] * DOT[min(d, 2)] + dash


def parse_jianpu(text: str, title: str = "", source: str = "") -> Score:
    """jiko-official.top/delta 的简谱 DSL。"""
    warn_list: list[str] = []

    def warn(msg: str):
        if msg not in warn_list:
            warn_list.append(msg)

    title = title or "未命名"
    bpm, meter, key = BEAT_DEFAULT_BPM, "4/4", "1=C"
    body_lines = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("//") or line.startswith("#!"):
            continue
        m = re.match(r"^(TITLE|BPM|KEY|METER)\s*=\s*(.+)$", line, re.I)
        if m:
            k, v = m.group(1).upper(), m.group(2).strip()
            if k == "TITLE":
                title = v
            elif k == "BPM":
                try:
                    bpm = float(re.match(r"[\d.]+", v).group(0))
                except Exception:
                    warn(f"BPM 读不出来：{v}")
            elif k == "METER":
                meter = v
            else:
                key = v
            continue
        body_lines.append(line)

    # 反复线：把 ||: ... :|| 里的内容复制一遍
    body = "\n".join(body_lines)
    body = _expand_repeats(body)

    notes: list[Note] = []
    bar_beats, bar_index = 0.0, 1
    t = 0.0
    prev_idx = None
    for line in body.splitlines():
        for tok in line.split():
            if tok in ("|", "||", "|:", ":|", "||:", ":||", ":|:"):
                bar_beats, bar_index = 0.0, bar_index + 1
                continue
            if set(tok) == {"-"} and len(tok) >= 1 and not re.search(r"\d", tok):
                # 独立的 "-"：延长前一个音 1 拍 / 休止 1 拍（viz2 兼容写法）
                if prev_idx is not None and notes[prev_idx].pitch is not None:
                    notes[prev_idx].dur += len(tok)
                t += len(tok)
                bar_beats += len(tok)
                continue
            m = _TOKEN.match(tok)
            if not m:
                warn(f"看不懂的记号已跳过：{tok}")
                t += 1.0
                bar_beats += 1.0
                continue
            prefix, acc = m.group("prefix"), m.group("acc") or ""
            low, deg, high = m.group("low") or "", int(m.group("deg")), m.group("high") or ""
            dur = _dur_of(m.group("dur"), warn, tok)
            if len(low) and len(high):
                warn(f"同一个音不能同时有高低八度标记：{tok}")
            if prefix and len(set(prefix)) != len(prefix):
                warn(f"变调前缀重复：{tok}")
            if "L" in prefix and "R" in prefix:
                warn(f"不能同时用 L 和 R：{tok}")

            if deg == 0:                                   # 休止
                if prefix:
                    warn(f"休止符不能加变调前缀：{tok}")
                t += dur
                bar_beats += dur
                prev_idx = None
                continue

            oct_mark = len(high) - len(low)
            acc_off = 1 if acc in ("#", "♯") else (-1 if acc in ("b", "♭") else 0)
            pitch = keymap.BASE_NOTE + keymap.DEG_SEMITONE[deg] + 12 * oct_mark + acc_off
            if "L" in prefix:                              # 左键降调 = 降八度
                pitch -= 12
            if "R" in prefix:                              # 右键升调 = 升八度
                pitch += 12
            if "M" in prefix:                              # 中键 = 升半音
                pitch += 1
            notes.append(Note(pitch, round(t, 6), dur, False, tok, measure=bar_index))
            prev_idx = len(notes) - 1
            if m.group("tie"):
                notes[-1].tie = True
            t += dur
            bar_beats += dur
    _merge_ties(notes, warn)
    return Score(title, bpm, meter, key, notes, source, "简谱", warn_list)


def _expand_repeats(body: str) -> str:
    """把 ||: xxx :|| 段落的行内容复制一遍（简单反复，不处理嵌套）。"""
    out, buf, inside = [], [], False
    for line in body.splitlines():
        if "||:" in line:
            inside = True
            buf = [line.split("||:", 1)[1]]
            continue
        if inside:
            if ":||" in line:
                buf.append(line.split(":||", 1)[0])
                inside = False
                out.append("||:")
                out.extend(buf)
                out.append(":||")
                out.append("||:")
                out.extend(buf)
                out.append(":||")
            else:
                buf.append(line)
            continue
        out.append(line)
    if inside:
        out.extend(buf)
    return "\n".join(out)


def _merge_ties(notes: list, warn) -> None:
    """把连音线连接的两个同音高音符合并成一个长音（原地修改 notes）。"""
    i = 0
    while i < len(notes) - 1:
        a, b = notes[i], notes[i + 1]
        if a.tie:
            if a.pitch is None or b.pitch != a.pitch:
                warn(f"连音线两端音高不一致，按断开处理：{a.text} {b.text}")
                a.tie = False
            else:
                a.dur = round(a.dur + b.dur, 6)
                a.tie = b.tie
                del notes[i + 1]
                continue
        i += 1
    if notes and notes[-1].tie:
        notes[-1].tie = False


# ================================================================ viz2 格式
_VIZ_PREFIX = {"b": -12, "^": +12, "#": +1}


def parse_viz(text: str, title: str = "", source: str = "") -> Score:
    """ChiZhou6/harmonica-visualizer 的文本谱：TITLE=/BPM= 头 + <b # ^> 前缀 + 1..7/8。"""
    warn_list: list[str] = []
    title = title or "未命名"
    bpm = BEAT_DEFAULT_BPM
    notes: list[Note] = []
    t = 0.0
    bar_no = 1
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        head = line.split("=", 1)
        if len(head) == 2 and head[0].strip().upper() in ("BPM", "TITLE"):
            if head[0].strip().upper() == "BPM":
                try:
                    bpm = float(re.match(r"[\d.]+", head[1].strip()).group(0))
                except Exception:
                    warn_list.append(f"BPM 读不出来：{head[1]}")
            else:
                title = head[1].strip() or title
            continue
        for tok in line.split():
            if tok in ("|", "-") and tok == "|":
                bar_no += 1
                continue
            if tok in ("-", "0-"):
                if notes and notes[-1].pitch is not None:
                    notes[-1].dur += 1.0
                t += 1.0
                continue
            pref, body = "", tok
            while body and body[0] in "b#^":
                pref += body[0]
                body = body[1:]
            suf = ""
            while body and body[-1] in "_.-":
                suf = body[-1] + suf
                body = body[:-1]
            u, d, dash = suf.count("_"), suf.count("."), suf.count("-")
            ext = 0
            if not body:
                warn_list.append(f"看不懂的记号已跳过：{tok}")
                t += 1.0 + ext
                continue
            if body in ("0",):
                t += UNDER[min(u, 3)] * DOT[min(d, 2)] + dash
                continue
            if body in ("8", "i", "I"):
                deg = 8
            elif body.isdigit() and 1 <= int(body) <= 7:
                deg = int(body)
            else:
                warn_list.append(f"看不懂的记号已跳过：{tok}")
                t += 1.0
                continue
            off = keymap.KEY_OFFSET[","] if deg == 8 else keymap.DEG_SEMITONE[deg]
            pitch = keymap.BASE_NOTE + off + sum(_VIZ_PREFIX[c] for c in set(pref))
            dur = UNDER[min(u, 3)] * DOT[min(d, 2)] + dash
            notes.append(Note(pitch, round(t, 6), dur, False, tok, measure=bar_no))
            t += dur
    return Score(title, bpm, "4/4", "1=C", notes, source, "viz2", warn_list)


# ================================================================ DFH tab
DFH_RHYTHM = {"1": 4.0, "2·": 3.0, "2": 2.0, "4·": 1.5, "4": 1.0,
              "8·": 0.75, "8": 0.5, "16·": 0.375, "16": 0.25, "32": 0.125}


def is_dfh_tab(text: str) -> bool:
    s = str(text)
    return "键位标记" in s or ("小节" in s and "键位" in s and "节奏" in s)


def _dfh_beats(tok: str) -> float:
    tok = tok.strip()
    if tok.endswith("b"):
        try:
            return float(tok[:-1])
        except ValueError:
            return 1.0
    return DFH_RHYTHM.get(tok, 1.0)


def _dfh_mods(marks: str) -> set:
    s = set(str(marks))
    mods = set()
    if "#" in s:
        mods.add(keymap.MOUSE_SHARP)
    if "-" in s:
        mods.add(keymap.MOUSE_DOWN)
    if "+" in s:
        mods.add(keymap.MOUSE_UP)
    return mods


def parse_dfh(text: str, title: str = "", source: str = "") -> Score:
    """Dr-hydra 的「小节 N (4/4) / 简谱 / 键位 / 节奏」文本谱。"""
    warn_list: list[str] = []
    title = title or "未命名"
    bpm, notes = BEAT_DEFAULT_BPM, []
    cur, mlen, in_m, keys, rhy = 0.0, 4.0, False, [], []

    # 小节号是谱面自己写的，用它对齐小节起点：某个小节时值不足/超出时，
    # 只影响本小节，绝不把后面的音拽到前面去（照搬参考实现的说法）。

    meter = ""                                  # 谱面自己写的拍号（以前硬编码 4/4）

    def flush():
        nonlocal cur, keys, rhy, in_m
        off = 0.0
        for ktok, rtok in zip(keys, rhy):
            m = re.match(r"^(.)(.*)$", ktok.strip())
            kk = m.group(1).upper() if m.group(1) != "," else ","
            if not m or kk not in keymap.KEY_OFFSET:
                warn_list.append(f"键位记号认不出：{ktok}")
                continue
            mods = _dfh_mods(m.group(2))
            pitch = keymap.pitch_of(kk, mods)
            dur = _dfh_beats(rtok)
            notes.append(Note(pitch, round(cur + off, 6), dur, False, ktok, measure=bno))
            off += dur
        cur += mlen
        keys, rhy, in_m = [], [], False

    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or "键位标记" in line:
            continue
        if "三角洲口琴谱" in line and not line.startswith("BPM"):
            title = line.split("—")[0].strip() or title
            continue
        m = re.match(r"^BPM\s+([\d.]+)", line)
        if m:
            bpm = float(m.group(1))
            continue
        m = re.match(r"^小节\s+(\d+)\s*\((\d+)/(\d+)\)(.*)$", line)
        if m:
            if in_m:
                flush()
            bno = int(m.group(1))                   # 谱面自己写的小节号
            if not meter:
                meter = f"{m.group(2)}/{m.group(3)}"
            mlen = int(m.group(2)) * 4.0 / int(m.group(3))
            if "—" in m.group(4):
                cur = bno * mlen                    # 空小节：直接落到该小节末尾
            else:
                cur = max(cur, (bno - 1) * mlen)     # 起点对齐小节线，不拽动后面的音
                in_m = True
            continue
            continue
        if line.startswith("键位"):
            keys = line[2:].strip().split()
        elif line.startswith("节奏"):
            rhy = line[2:].strip().split()
    if in_m:
        flush()
    # 该格式的节奏列不含音符之间的休止，只能紧挨排布 —— 小节边界仍是准的
    return Score(title, bpm, meter or "4/4", "1=C", notes, source, "DFH", warn_list)


# ================================================================ 导出 jianpu
def format_jianpu(score: Score, with_header: bool = True) -> str:
    """导出成 jiko 站点可直接粘贴的简谱文本（非整拍时值用「:精确拍数」写法）。"""
    lines = []
    if with_header:
        lines += [f"TITLE={score.title}", f"BPM={score.bpm:g}",
                  f"KEY={score.key}", f"METER={score.meter}", ""]
    bpm_sec = score.beat_sec
    del bpm_sec
    per = score.beats_per_measure()
    cur, bar = 0.0, 1
    toks: list[str] = []
    for n in score.notes:
        gap = n.start - cur
        while gap > 1e-6:                       # 用休止符补空档
            g = min(gap, per)
            if g <= 1e-6:
                break
            toks.append(_dur_token("0", g))
            cur += g
            gap -= g
        if n.pitch is None:
            toks.append(_dur_token("0", n.dur))
        else:
            toks.append(_dur_token(keymap.solfege(n.pitch), n.dur))
        cur += n.dur
        while cur >= per * bar - 1e-6:
            toks.append("|")
            bar += 1
    out = []
    per_line = int(per * 2) or 8
    for i in range(0, len(toks), per_line):
        out.append(" ".join(toks[i:i + per_line]))
    return "\n".join(lines + out) + "\n"


def _dur_token(head: str, dur: float) -> str:
    """把 (记号, 拍数) 写成简谱的时值写法。"""
    d = round(dur, 6)
    if abs(d - 1.0) < 1e-6:
        return head
    if abs(d - UNDER[1]) < 1e-6:
        return head + "_"
    if abs(d - UNDER[2]) < 1e-6:
        return head + "__"
    if abs(d - UNDER[3]) < 1e-6:
        return head + "___"
    if abs(d - DOT[1]) < 1e-6:
        return head + "."
    if abs(d - DOT[2]) < 1e-6:
        return head + ".."
    if d > 1.0 and abs(d - round(d)) < 1e-6 and round(d) <= 8:
        return head + "-" * (int(round(d)) - 1)
    return f"{head}:{d:g}"


# ================================================================ 入口
# 判别依据只看「两套语法独有的写法」，避免 # 前缀这种共同点误判：
#   简谱(jiko)：L/M/R 变调前缀、音符/拍数 或 音符:拍数
#   viz2      ：b/^ 变调前缀、独立的高音 8
JIANPU_HINT = re.compile(r"(?:^|\s)[LMR]{1,2}[#b♯♭]?[0-7′]*[_.\-:/(\s]|"
                         r"(?:^|\s)[#b♯♭]?[0-7′]{1,3}[:/][\d.]")
VIZ_HINT = re.compile(r"(?:^|\s)[b^][#b^]?[0-7](?:[_.\-]{0,4})?(?:\s|$)|"
                      r"(?:^|\s)8(?:[_.\-]{0,4})?(?:\s|$)")


def detect_format(text: str) -> str:
    """判谱面格式：DFH tab / 简谱 DSL(jiko) / viz2 简谱。"""
    if is_dfh_tab(text):
        return "dfh"
    if JIANPU_HINT.search(text):
        return "jianpu"
    if VIZ_HINT.search(text):
        return "viz2"
    return "jianpu"


def clamp_overlaps(sc: "Score") -> int:
    """口琴一次只能吹一个音：把与前一个音重叠的尾巴截掉。

    不做这件事的后果很实在：时间轴上会出现「同一个键还没松手又按下去」，
    以及导出简谱时后一个音被顺延（因为简谱是顺序记号，表达不了重叠）。
    """
    ns = sorted(sc.notes, key=lambda x: (x.start, -x.dur))
    n = 0
    for a, b in zip(ns, ns[1:]):
        if a.pitch is None or b.start <= a.start + 1e-9:
            continue
        if b.start < a.start + a.dur - 1e-9:
            a.dur = round(max(0.01, b.start - a.start), 6)
            n += 1
    return n


def squeeze_short_rests(sc: "Score", min_beats: float) -> int:
    """把短于 min_beats 的休止（两音之间的空档）抹平：其后的音整体提前，旋律连起来。

    图片转录出来的谱子会在快速音群里插一个 1/4 拍休止（`0__`），本意可能只是标记
    "这里是下一个音"，但真弹出来就是 239ms 的空档 —— 快速跑句里听感就是"一顿"。
    这是**可选的听感修正**，默认关（min_beats=0），因为休止是谱面内容，不该偷偷改。

    返回被抹平的处数。只动 start，不动 dur / 音高。
    """
    ns = sc.notes
    if len(ns) < 2 or min_beats <= 0:
        return 0
    shift, fixed = 0.0, 0
    prev_end = ns[0].start + ns[0].dur
    for i in range(1, len(ns)):
        s = round(ns[i].start - shift, 6)
        gap = s - prev_end
        if 1e-6 < gap <= min_beats + 1e-9:
            shift = round(shift + gap, 6)
            s = round(ns[i].start - shift, 6)
            fixed += 1
        ns[i].start = s
        prev_end = round(s + ns[i].dur, 6)
    return fixed


def parse_any(path: str, text: str | None = None, **kw) -> Score:
    """按扩展名/内容自动选解析器。"""
    sc = _parse_any_inner(path, text, **kw)
    n = clamp_overlaps(sc)
    if n:
        sc.warnings.append(f"{n} 处音与上一个音重叠，已按单音节口琴处理（截到下一个音开始）")
    return sc


AUDIO_EXT = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".wma")


def _parse_any_inner(path: str, text: str | None = None, **kw) -> Score:
    name = os.path.basename(path) if path else "未命名"
    title = os.path.splitext(name)[0]
    if path and path.lower().endswith(AUDIO_EXT):        # 音频：先于读文本，别把 MP3 当 UTF-8 读
        from audio_in import read_song as read_audio
        notes, info = read_audio(path, **{k: v for k, v in kw.items()
                                          if k in ("bpm", "fmin", "fmax", "min_dur", "conf_min", "key")})
        s = Score(title, info["bpm"], "4/4", info.get("key") or "1=C",
                  [Note(p, b, d, False, "") for p, b, d in notes], path, "AUDIO", [])
        s.warnings.append(
            f"从音频听出来的：{info['seconds']:.1f}s / 有声帧 {info['voiced']}/{info['frames']} / "
            f"平均置信度 {info['conf_mean']} / 丢掉过短段 {info['dropped_short']} 个"
            f"（信息型，不是错误；单声部效果最好，混音复杂的会跟着最突出的乐器走）")
        if info.get("bpm_estimated") and "bpm" not in kw:
            s.warnings.append(f"BPM 是从起音间隔估的 {info['bpm_estimated']}，可用 --bpm 覆盖")
        return s
    if text is None:
        text = open(path, encoding="utf-8", errors="replace").read()
    if path and path.lower().endswith((".mid", ".midi")):
        from midi_in import read_song
        notes, info = read_song(path, **{k: v for k, v in kw.items()
                                         if k in ("track", "prefer_name", "melody", "merge",
                                                  "tracks_wanted")})
        s = Score(title, info["bpm"], "4/4", "1=C",
                  [Note(p, b, d, False, "") for p, b, d in notes], path, "MIDI", [])
        s.warnings.append(f"选用轨道 {info['track_name']}，丢弃和弦音 {info['dropped']} 个"
                          f"（信息型，不是错误）")
        return s
    if path and path.lower().endswith(".json"):
        raise ValueError("JSON 事件表请直接用 play.py 载入（本模块负责文本谱/MIDI）")
    fmt = detect_format(text)
    if fmt == "dfh":
        return parse_dfh(text, title, path)
    if fmt == "viz2":
        return parse_viz(text, title, path)
    return parse_jianpu(text, title, path)


def report(score: Score) -> str:
    """曲谱统计（对齐站点「播放器统计」：总时长 / 音符数 / 输入事件数）。"""
    per = score.beats_per_measure()
    est = int(score.total_beats / per + 0.999) if per else 0
    numbered = {n.measure for n in score.notes if getattr(n, "measure", 0)}
    # 谱面把小节线写全了才用真实小节数（弱起/末尾短小节/变拍号），否则按拍数估——避免
    # 那种整首只写了几条竖线、按小节线数会显示成「1 小节」的谱面误导人。
    src = bool(numbered) and max(numbered) >= 0.6 * est
    bar_txt = f"{max(numbered)} 小节" if src else f"约 {est} 小节"
    sung = [n for n in score.notes if n.pitch is not None]
    lo = min((n.pitch for n in sung), default=0)
    hi = max((n.pitch for n in sung), default=0)
    out = [f"《{score.title}》 · {score.fmt} 格式 · {score.bpm:g} BPM · {score.meter} · {score.key}",
           f"  音符 {len(sung)} 个（休止间隔不计）· 总拍数 {score.total_beats:.2f}"
           f" · {bar_txt} · 时长 {score.seconds:.1f}s = {int(score.seconds // 60)}分{score.seconds % 60:.0f}秒",
           f"  音域 {keymap.solfege(lo)}..{keymap.solfege(hi)}（MIDI {lo}..{hi}）"]
    # 小节拍数校验
    bad = sum(1 for n in score.notes
              if per and n.start - int(n.start / per) * per > per + 1e-6)
    if bad:
        out.append(f"  ⚠ {bad} 个音符的起点落在小节之外（超出 {per:g} 拍的小节长度）")
    for w in score.warnings[:6]:
        out.append(f"  · {w}")
    if len(score.warnings) > 6:
        out.append(f"  · 另有 {len(score.warnings) - 6} 条同类提示")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    paths = sys.argv[1:] or sorted(
        [os.path.join("songs", f) for f in os.listdir("songs")
         if f.lower().endswith((".jianpu", ".txt"))])
    ok = 0
    for p in paths:
        try:
            s = parse_any(p)
            print(report(s))
            ok += 1
        except Exception as e:
            print(f"{p}: ✗ {type(e).__name__}: {e}")
        print()
    print(f"解析成功 {ok}/{len(paths)}")


# ================================================================ 谱面 → play.py 事件表
def to_score_table(score, base_octave="auto", transpose: int = 0, skip_out_of_range: bool = True):
    """Score → (事件表, 统计)。超出口琴音域的音按休止处理并计数（不静默改变曲速）。"""
    per = score.beats_per_measure() or 4.0
    sung = [n for n in score.notes if n.pitch is not None]
    pitches = [n.pitch + transpose for n in sung]
    base = keymap.auto_base_octave(pitches)[0] if base_octave in ("auto", None, "") else int(base_octave)

    # 小节起点：优先用解析器自报的小节号（弱起、变拍号的谱面才不会整体错位一格）；
    # 解析器没给就退回「从 0 开始、每 per 拍一小节」。
    keys: list[int] = []
    ok = True
    last = 0
    for n in score.notes:
        m = int(getattr(n, "measure", 0) or 0)
        if m:
            last = m
        elif last == 0:
            ok = False
            break
        keys.append(last if last else 1)
    if not ok or not keys:
        keys = [int(n.start // per) + 1 for n in score.notes]
        grid = True
    else:
        grid = False
    m_start: dict[int, float] = {}
    for n, k in zip(score.notes, keys):
        if k not in m_start:
            m_start[k] = n.start          # 该小节第一个事件（含休止）的绝对起拍

    by_m: dict[int, list] = {}
    out_of_range, total, folded, folded_notes = 0, 0, 0, []
    for n, k in zip(score.notes, keys):
        if n.pitch is None:
            continue
        total += 1
        mi = k - 1
        off = round(n.start - m_start[k], 6)
        p = n.pitch + transpose + keymap.OCTAVE * (base - 4)
        key, mods = keymap.map_pitch(p)[:2]
        if key is None:
            # 超出可弹音域(48..85) → 按整八度折回。宁可换个八度，也不能让这个音消失：
            # 静音 = 缺音，是实机最难查的一类问题（见 README「缺音的三种来源」）。
            for octs in range(1, 6):
                hit = [c for c in (p - keymap.OCTAVE * octs, p + keymap.OCTAVE * octs)
                       if keymap.map_pitch(c)[0] is not None]
                if hit:
                    p = hit[0]
                    key, mods = keymap.map_pitch(p)[:2]
                    folded += 1
                    folded_notes.append(keymap.solfege(p))
                    break
        if key is None:
            out_of_range += 1
            if skip_out_of_range:
                by_m.setdefault(mi, []).append(dict(beat=off, beats=round(n.dur, 6), key=None,
                                                    mods=[], note=keymap.solfege(p)))
                continue
        by_m.setdefault(mi, []).append(dict(beat=off, beats=round(n.dur, 6), key=key,
                                            mods=sorted(mods), note=keymap.solfege(p)))

    n_m = max(by_m.keys(), default=-1) + 1
    measures = []
    for i in range(n_m):
        evs = sorted(by_m.get(i, []), key=lambda e: e["beat"])
        used = max((e["beat"] + e["beats"] for e in evs), default=0.0)
        measures.append(dict(index=i + 1, beats=round(used if not grid else max(per, used), 6), events=evs,
                             start_beat=round(m_start.get(i + 1, i * per), 6),
                             confident=True))
    table = dict(title=score.title, bpm=score.bpm, meter=score.meter, key=score.key,
                 beats_per_measure=per, base_octave=base, transpose=transpose,
                 source=score.source, fmt=score.fmt, measures=measures)
    played = [p + keymap.OCTAVE * (base - 4) for p in pitches]   # 实际会弹出来的音高
    stats = dict(notes=total, playable=total - out_of_range, out_of_range=out_of_range,
                 folded=folded, folded_notes=sorted(set(folded_notes)),
                 base_octave=base, measures=n_m,
                 beats=round(score.total_beats, 3), seconds=round(score.seconds, 2),
                 lo=min(played, default=0), hi=max(played, default=0),
                 src_lo=min(pitches, default=0), src_hi=max(pitches, default=0),
                 out_notes=sorted({keymap.solfege(n.pitch + transpose + keymap.OCTAVE * (base - 4))
                                   for n in sung
                                   if keymap.map_pitch(n.pitch + transpose
                                                       + keymap.OCTAVE * (base - 4))[0] is None}))
    return table, stats

def from_score_table(tab: dict) -> Score:
    """play.py 事件表 → Score（逆向）。这样图片谱面也能导出成人人可读的简谱。

    pitch_of(键, 修饰键) 得到口琴实际音高，再减掉当初的八度/半音移调还原成谱面音高。
    """
    per = float(tab.get("beats_per_measure") or 4.0)
    base = int(tab.get("base_octave") or 4)
    tr = int(tab.get("transpose") or 0)
    back = keymap.OCTAVE * (base - 4) + tr
    sc = Score(title=tab.get("title") or "未命名", bpm=float(tab.get("bpm") or 125),
               meter=tab.get("meter") or "4/4", key=tab.get("key") or "1=C",
               source=tab.get("source") or "", fmt="事件表")
    for mi, m in enumerate(tab.get("measures") or [], 1):
        for ev in m.get("events") or []:
            start = (mi - 1) * per + float(ev.get("beat") or 0.0)
            dur = float(ev.get("beats") or 1.0)
            if not ev.get("key"):
                sc.notes.append(Note(None, start, dur, text="0"))
                continue
            pitch = keymap.pitch_of(ev["key"], ev.get("mods") or ())
            if pitch is None:
                continue
            sc.notes.append(Note(pitch - back, start, dur, text=ev.get("note") or ""))
    return sc
