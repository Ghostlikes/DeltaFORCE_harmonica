#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标准 MIDI 文件（.mid/.midi）读取器 —— 纯 Python，无第三方依赖。

对照 ChickenD233/midikey-player 的 MidiKeyPlayer/Midi/MidiLoader.cs 实现：
    * MThd / MTrk 解析、VLQ 变长量、running status
    * 音轨名（meta 0x03）、速度（meta 0x51）、拍号（meta 0x58）
    * 选音轨（默认取音符最多的那一条）—— 对应站点里的「选择旋律音轨」
    * 同一时刻的和弦只保留一个音 —— 对应站点里「同一和弦组只能保留一个音」
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

DEFAULT_TEMPO = 500_000          # 120 BPM


@dataclass
class TrackInfo:
    index: int
    name: str
    notes: int                   # note-on 数量
    channels: set = field(default_factory=set)
    program: int | None = None   # 第一个 program change


def _vlq(data: bytes, i: int) -> tuple[int, int]:
    """变长量（每字节 7 位，最高位是续接标志）。"""
    val = 0
    while True:
        b = data[i]
        i += 1
        val = (val << 7) | (b & 0x7F)
        if not b & 0x80:
            return val, i


def read_midi(path: str):
    """读 .mid → (division, tracks, infos)。

    tracks[i] = [(tick, kind, payload), ...]，kind ∈ {'on','off','tempo','name','ts','other'}
    """
    raw = open(path, "rb").read()
    if raw[:4] != b"MThd":
        raise ValueError("不是标准 MIDI 文件（缺 MThd）")
    hlen = struct.unpack(">I", raw[4:8])[0]
    fmt, ntrks, division = struct.unpack(">HHH", raw[8:14])
    pos = 8 + hlen
    tracks, infos = [], []
    for ti in range(ntrks):
        if pos + 8 > len(raw) or raw[pos:pos + 4] != b"MTrk":
            break
        tlen = struct.unpack(">I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8: pos + 8 + tlen]
        pos += 8 + tlen
        evs, tick, i, status = [], 0, 0, None
        name, notes, channels, program = f"轨道{ti + 1}", 0, set(), None
        while i < len(body):
            dt, i = _vlq(body, i)
            tick += dt
            if i >= len(body):
                break
            b = body[i]
            if b & 0x80:                     # 新状态字节
                status = b
                i += 1
            # 否则沿用上一个状态字节（running status）
            hi = status & 0xF0
            if status == 0xFF:               # meta
                mtype = body[i]
                i += 1
                mlen, i = _vlq(body, i)
                mdata = body[i:i + mlen]
                i += mlen
                if mtype == 0x51 and len(mdata) == 3:
                    evs.append((tick, "tempo", (mdata[0] << 16) | (mdata[1] << 8) | mdata[2]))
                elif mtype == 0x03:
                    name = mdata.decode("utf-8", "replace") or name
                    evs.append((tick, "name", name))
                elif mtype == 0x58 and len(mdata) >= 2:
                    evs.append((tick, "ts", (mdata[0], 1 << mdata[1])))
                continue
            if status in (0xF0, 0xF7):       # sysex
                mlen, i = _vlq(body, i)
                i += mlen
                continue
            if hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):      # 两字节参数
                d1, d2 = body[i], body[i + 1]
                i += 2
                ch = status & 0x0F
                if hi == 0x90 and d2 > 0:
                    evs.append((tick, "on", (d1, d2, ch)))
                    notes += 1
                    channels.add(ch)
                elif hi == 0x80 or (hi == 0x90 and d2 == 0):
                    evs.append((tick, "off", (d1, ch)))
                continue
            if hi in (0xC0, 0xD0):           # 一字节参数
                d1 = body[i]
                i += 1
                if hi == 0xC0 and program is None:
                    program = d1
                continue
            i += 1                           # 认不出的，跳过
        tracks.append(evs)
        infos.append(TrackInfo(ti, name, notes, channels, program))
    if not tracks:
        raise ValueError("MIDI 里没有可解析的音轨")
    return division, tracks, infos


PERCUSSION_CHANNEL = 9          # MIDI 通道 10 = 打击乐（midikey 的 MidiLoader 同样单独标注）


def pick_track(infos, want: int | None = None, prefer_name: str | None = None) -> int:
    """挑音轨：显式指定 > 名字命中 > 非打击乐里音符最多（打击乐一律不参与）。"""
    if want is not None:
        return want
    if prefer_name:
        for t in infos:
            if prefer_name.lower() in t.name.lower():
                return t.index
    ok = [t for t in infos if t.notes > 0 and PERCUSSION_CHANNEL not in t.channels]
    if not ok:
        ok = [t for t in infos if t.notes > 0]
    if not ok:
        ok = infos
    return max(ok, key=lambda t: t.notes).index


def track_notes(tracks, index: int):
    """取某轨的音符 → [(pitch, start_tick, end_tick, velocity)]（未按音高配对时用先进先出）。"""
    open_at: dict[tuple[int, int], list] = {}
    out = []
    for tick, kind, payload in tracks[index]:
        if kind == "on":
            pitch, vel, ch = payload
            open_at.setdefault((pitch, ch), []).append((tick, vel))
        elif kind == "off":
            pitch, ch = payload
            stack = open_at.get((pitch, ch))
            if stack:
                st, vel = stack.pop(0)
                out.append((pitch, st, max(tick, st + 1), vel))
    for (pitch, ch), stack in open_at.items():        # 没收到 note-off 的
        for st, vel in stack:
            out.append((pitch, st, st + 1, vel))
    out.sort(key=lambda n: (n[1], n[0]))
    return out


def tempo_map(tracks, division):
    """合并所有轨的速度信息 → [(tick, usec_per_beat), ...]（按 tick 排序，首项必为 0 时刻）。"""
    marks = [(0, DEFAULT_TEMPO)]
    for evs in tracks:
        for tick, kind, payload in evs:
            if kind == "tempo":
                marks.append((tick, payload))
    marks.sort()
    merged, last = [], None
    for tick, tempo in marks:
        if last is None or tempo != last:
            merged.append((tick, tempo))
            last = tempo
    if not merged or merged[0][0] != 0:
        merged.insert(0, (0, DEFAULT_TEMPO))
    return merged


def tick_to_beat(division: int, ticks: int, ticks_per_beat: int | None = None) -> float:
    """tick → 拍。division 的高位为 1 时是 SMPTE 时间码（这里按帧率粗算）。"""
    if ticks_per_beat:
        return ticks / float(ticks_per_beat)
    if division & 0x8000:
        frames = ((division >> 8) & 0x7F) * 256 + (division & 0xFF)   # 保守：按帧数当拍
        return ticks / float(max(frames, 1))
    return ticks / float(max(division, 1))


def avg_pitch(tracks, index: int) -> float:
    ns = track_notes(tracks, index)
    return sum(n[0] for n in ns) / len(ns) if ns else 0.0


def read_song(path: str, track: int | None = None, prefer_name: str | None = None,
              melody: str = "highest", chord_window_ticks: int = 12,
              merge: bool = False, tracks_wanted=None):
    """MIDI → (notes, info)。

    notes = [(pitch, start_beat, dur_beats)]（已按「同一和弦只留一个音」整理）

    选轨规则（对齐 midikey 的「选择旋律音轨」体验）：
      * 打击乐轨（通道 10）一律排除；
      * 默认 auto：在非打击乐轨里挑**平均音高最高**的一条 —— 主旋律几乎总是最高声部；
      * merge=True：把所有非打击乐轨合起来，同一时刻只留最高音（合奏合并）；
      * track=N / tracks_wanted=[..]：完全手动指定。
    """
    division, tracks, infos = read_midi(path)
    if tracks_wanted:
        used = list(tracks_wanted)
    elif track is not None:
        used = [track]
    elif merge:
        used = [t.index for t in infos if t.notes > 0 and PERCUSSION_CHANNEL not in t.channels] or \
               [t.index for t in infos if t.notes > 0]
    else:
        cand = [t for t in infos if t.notes > 0 and PERCUSSION_CHANNEL not in t.channels] or \
               [t for t in infos if t.notes > 0]
        if not cand:
            raise ValueError("MIDI 里没有任何音符")
        if prefer_name:
            hit = [t for t in cand if prefer_name.lower() in t.name.lower()]
            used = [hit[0].index] if hit else [max(cand, key=lambda t: avg_pitch(tracks, t.index)).index]
        else:
            used = [max(cand, key=lambda t: avg_pitch(tracks, t.index)).index]

    raw = []
    for idx in used:
        raw.extend(track_notes(tracks, idx))
    if not raw:
        raise ValueError(f"轨道 {[i + 1 for i in used]} 里没有音符")

    # 同一时刻附近的和弦 → 只留一个（melody=highest 留最高音，lowest 留最低音）
    raw.sort(key=lambda n: (n[1], n[0]))
    kept, dropped = [], 0
    for pitch, st, en, vel in raw:
        if kept and st - kept[-1][1] <= chord_window_ticks and pitch != kept[-1][0]:
            prev = kept[-1]
            better = pitch > prev[0] if melody == "highest" else pitch < prev[0]
            if better:
                kept[-1] = (pitch, prev[1], max(en, prev[2]), vel)
            dropped += 1
            continue
        kept.append((pitch, st, en, vel))

    # tick → 拍；去掉被前一个音盖住的（同音高重叠）
    notes, last_end = [], -1.0
    for pitch, st, en, vel in kept:
        sb = tick_to_beat(division, st)
        eb = tick_to_beat(division, en)
        if sb < last_end - 1e-6:
            sb = last_end
        dur = max(eb - sb, 1 / 8)
        if sb < 0:
            sb = 0.0
        notes.append((pitch, round(sb, 6), round(dur, 6)))
        last_end = sb + dur

    tmap = tempo_map(tracks, division)
    bpm = round(60_000_000 / tmap[0][1], 3)
    names = "、".join(f"{i + 1}「{infos[i].name}」" for i in used)
    info = dict(bpm=bpm, division=division, track=used[0], tracks_used=used, track_name=names,
                tracks=infos, dropped=dropped, tempo_changes=len(tmap) - 1)
    return notes, info


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        notes, info = read_song(path)
        print(f"{path}")
        print(f"  速度 {info['bpm']:g} BPM · division={info['division']} · "
              f"选用轨道 {info['track'] + 1}「{info['track_name']}」· 丢弃和弦音 {info['dropped']}")
        for t in info['tracks']:
            print(f"    轨道{t.index + 1:>2} {t.name[:28]:<28} 音符 {t.notes:>5} 通道 {sorted(t.channels)}")
        print(f"  音符 {len(notes)} 个，前 8 个：{notes[:8]}")
