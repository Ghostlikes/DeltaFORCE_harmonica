#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三角洲行动 · 口琴键位与音高映射。

照搬 ChickenD233/midikey-player 的
    MidiKeyPlayer/Engine/KeymapProfile.cs → BuildChromatic8()   （默认方案「8 键半音」）
    MidiKeyPlayer/Engine/NoteMapper.cs    → Map / InRange / AutoBaseOctave
    MidiKeyPlayer/Engine/KeymapProfile.cs → ResolveMinNote / ResolveMaxNote

权威口径（原注释）：
    一排 8 个键 Z X C V B N M , 是 do..高音 do（自然音），
    鼠标左键降八度、右键升八度、中键升半音。能弹 48..85（MIDI 音高号）。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 键位表
# (键名, 相对 BaseNote 的半音偏移)：Z=C do, X=D re, C=E mi, V=F fa,
# B=G sol, N=A la, M=B si, ,=高音 do
KEYS: tuple[tuple[str, int], ...] = (
    ("Z", 0), ("X", 2), ("C", 4), ("V", 5), ("B", 7), ("N", 9), ("M", 11), (",", 12),
)
KEY_OFFSET = dict(KEYS)
OFFSET_KEY = {off: k for k, off in KEYS}          # 首匹配（, 的 12 优先于 Z+八度）

BASE_NOTE = 60            # C4：谱面里的「1」
OCTAVE = 12

# 鼠标三键的角色（与游戏内完全一致：左=降八度、中=升半音、右=升八度）
MOUSE_DOWN, MOUSE_SHARP, MOUSE_UP = "left", "middle", "right"

def _extent() -> tuple[int, int]:
    """照搬 ResolveMinNote / ResolveMaxNote：键位偏移张角 ± 八度键。"""
    offs = [o for _, o in KEYS]
    return BASE_NOTE + min(offs) - OCTAVE, BASE_NOTE + max(offs) + OCTAVE + 1


MIN_NOTE, MAX_NOTE = _extent()                     # 48 .. 85

# 简谱音级（1=C）→ 半音
DEG_SEMITONE = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
SEMITONE_DEG = {v: k for k, v in DEG_SEMITONE.items()}
DEG_SOLFEGE = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7"}


def in_range(pitch: int) -> bool:
    """这个音高能不能弹得出来。"""
    return MIN_NOTE <= pitch <= MAX_NOTE


def _try_relative(want: int):
    """把「相对 1 的半音数」解成 (键, 是否升半音, 八度偏移)。

    照搬 NoteMapper.Map 的查找顺序：先不带升号、再带升号；八度偏移 0 → +1 → -1。
    """
    for oct_off in (0, 1, -1):
        for key, off in KEYS:
            if off + OCTAVE * oct_off == want:
                return key, False, oct_off
    for oct_off in (0, 1, -1):
        for key, off in KEYS:
            if off + OCTAVE * oct_off + 1 == want:
                return key, True, oct_off
    return None


def map_pitch(pitch: int, base_octave: int = 4):
    """MIDI 音高 → (键, 修饰键集合, 说明)。弹不出来时返回 (None, set(), 原因)。

    注意：游戏口琴的实际音高由「键 + 变调键」唯一决定（Z=C4 是硬件定死的），
    所以这里是**绝对映射**，base_octave 只是为了让老调用方少改一行而保留的占位：
    真正要整体挪八度，请在谱面侧移调（to_score_table 的 base_octave / transpose），
    绝不在这里偷偷改变音高——否则会整曲高八度或低八度。
    """
    want = int(pitch) - BASE_NOTE
    got = _try_relative(want)
    if got is None:
        return None, set(), f"音高 {pitch} 超出口琴音域 {MIN_NOTE}..{MAX_NOTE}"
    key, sharp, oct_off = got
    mods = set()
    if oct_off < 0:
        mods.add(MOUSE_DOWN)
    elif oct_off > 0:
        mods.add(MOUSE_UP)
    if sharp:
        mods.add(MOUSE_SHARP)
    text = key if key != "," else "高音1"
    note = f"{key}"
    if mods:
        note += "+" + "+".join(sorted(mods))
    return key, mods, note


def pitch_of(key: str, mods) -> int | None:
    """(键, 修饰键) → MIDI 音高。map_pitch 的逆（用于把图片谱面换算成音高做移调/比对）。"""
    if key not in KEY_OFFSET:
        return None
    m = set(mods or ())
    p = BASE_NOTE + KEY_OFFSET[key]
    if MOUSE_SHARP in m:
        p += 1
    if MOUSE_UP in m:
        p += OCTAVE
    if MOUSE_DOWN in m:
        p -= OCTAVE
    return p


def auto_base_octave(pitches, lo: int = 2, hi: int = 6) -> tuple[int, int]:
    """挑基准八度（= 谱面整体挪几个八度去贴合 48..85 的口琴音域）。

    判据优先级：①越界音最少 → ②挪得越少越好（保持原曲音区，不擅自升/降八度）
    → ③需要的变调键最少（变调键是逐帧采样里最容易丢的一步）。
    返回 (base_octave, 越界音数)。
    """
    pitches = [p for p in pitches if p]
    if not pitches:
        return 4, 0
    scored = []
    for base in range(lo, hi + 1):
        shift = OCTAVE * (base - 4)          # 谱面整体挪几个八度去贴合口琴音域
        bad = mods = 0
        for p in pitches:
            key, need, _ = map_pitch(p + shift)
            if key is None:
                bad += 1
            elif need:
                mods += 1
        scored.append((bad, abs(base - 4), mods, base))
    scored.sort()
    bad, _, _, base = scored[0]
    return base, bad


def solfege(pitch: int, base_octave: int = 4) -> str:
    """MIDI 音高 → 简谱写法（含 #、' 、, ），用于导出人类可读的谱面。"""
    rel = pitch - BASE_NOTE - OCTAVE * (base_octave - 4)
    oct_marks = rel // OCTAVE
    pc = rel - OCTAVE * oct_marks          # 0..11
    acc = ""
    if pc in SEMITONE_DEG:
        deg = SEMITONE_DEG[pc]
    else:
        deg = SEMITONE_DEG.get(pc - 1)
        acc = "#"
        if deg is None:
            return f"[{pitch}]"
    body = f"{acc}{deg}"
    if oct_marks > 0:
        return body + "'" * min(oct_marks, 2)
    if oct_marks < 0:
        # jiko 站内写法是「升降号在前、低八度逗号在后」：升4 低八度 = #,4（不是 ,#4）
        return f"{acc}{',' * min(-oct_marks, 2)}{deg}"
    return body


def describe_table() -> str:
    """人话键位表（照搬 build 注释里的说明）。"""
    lines = [
        f"键位：{' '.join(k for k, _ in KEYS)}  =  do re mi fa sol la si 高音do",
        f"鼠标左键 = 降八度(-12)   中键 = 升半音(+1)   右键 = 升八度(+12)",
        f"可弹音域：{MIN_NOTE}..{MAX_NOTE}（MIDI 音高号）"
        f" = {solfege(MIN_NOTE)} .. {solfege(MAX_NOTE)}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(describe_table())
    print()
    bad = 0
    for p in range(0, 128):
        key, mods, note = map_pitch(p)
        ok = in_range(p)
        if ok != (key is not None):
            bad += 1
            print(f"  ✗ 一致性错误 pitch={p} in_range={ok} map={note}")
    print(f"音域一致性自检：48..85 全部可映射、其余全部拒绝 → {'通过' if bad == 0 else f'{bad} 处不一致'}")
    print()
    print("抽样：", "  ".join(f"{p}={map_pitch(p)[2]}" for p in (48, 60, 61, 66, 72, 84, 85)))
    sys.exit(1 if bad else 0)
