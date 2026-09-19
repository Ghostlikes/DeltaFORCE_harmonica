#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest4.py — 音频导入（audio_in.py）自测。

不依赖任何外部音频文件：自己合成一段**已知旋律**（带谐波的口琴式音色），
编码成 MP3 和 WAV，再用 audio_in.read_song 听回来，逐个音对答案。
所以这个测试是可复现的、不涉及任何版权音频。

用法：python dev/selftest4.py        （在项目根目录跑，或从任何目录跑都行）
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np

import audio_in

PASS = FAIL = 0
FAILED = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✔ {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  ✗ {name}" + (f"  {detail}" if detail else ""))


NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def nname(m):
    return f"{NAMES[int(m) % 12]}{int(m) // 12 - 1}"


def synth(notes, bpm=120.0, sr=22050, gap=0.0):
    """notes=[(midi, 起拍, 时值拍)] → 单声道 float32 波形（口琴式音色 + 起落包络）。"""
    beat = 60.0 / bpm
    total = max(b + d for _, b, d in notes) + 1.0
    x = np.zeros(int(total * sr), dtype=np.float32)
    for midi, b, d in notes:
        f = 440.0 * 2 ** ((midi - 69) / 12)
        t0 = int((b + gap / 2) * beat * sr)
        t1 = int((b + d - gap / 2) * beat * sr)
        n = t1 - t0
        if n <= 0:
            continue
        t = np.arange(n) / sr
        env = np.minimum(1.0, np.minimum(t / 0.02, (n / sr - t) / 0.03)).clip(0, 1)
        w = sum(a * np.sin(2 * np.pi * f * k * t) for k, a in ((1, .6), (2, .25), (3, .12), (4, .06)))
        x[t0:t1] += (w * env * 0.28).astype(np.float32)
    return x, sr


def encode(x, sr, path, fmt):
    """用 PyAV 编码（mp3 走 libmp3lame，wav 直接写 PCM）。"""
    import av
    codec = {"mp3": "libmp3lame", "wav": "pcm_s16le"}[fmt]
    with av.open(path, "w", format=fmt) as out:
        st = out.add_stream(codec, rate=sr)
        if fmt == "mp3":
            st.bit_rate = 128000
        for i in range(0, len(x), 1024):
            chunk = np.clip(x[i:i + 1024] * 32767, -32768, 32767).astype(np.int16)[None, :]
            fr = av.AudioFrame.from_ndarray(chunk, format="s16", layout="mono")
            fr.sample_rate = sr
            for pkt in st.encode(fr):
                out.mux(pkt)
        for pkt in st.encode(None):
            out.mux(pkt)


TMP = os.path.join(os.path.expanduser("~"), ".harmonica_probe", "selftest4")
os.makedirs(TMP, exist_ok=True)

print("=== 1) YIN 音高检测本身 ===")
for freq, want in ((130.0, 130.0), (220.0, 220.0), (440.0, 440.0), (659.26, 659.26), (1200.0, 1200.0)):
    t = np.arange(int(2.0 * 22050)) / 22050
    x = np.zeros_like(t, dtype=np.float32)
    for k, a in ((1, .6), (2, .25), (3, .12), (4, .06)):
        x += (a * np.sin(2 * np.pi * freq * k * t)).astype(np.float32)
    f0, conf, _ = audio_in.yin_f0(x.astype(np.float32) * 0.3, 22050)
    got = float(np.median(f0[len(f0) // 4:3 * len(f0) // 4]))
    cents = 1200 * np.log2(got / want)
    check(f"{want}Hz 音高检测（偏差 {cents:+.0f} 音分）", abs(cents) < 20, f"检出 {got:.2f}Hz conf {np.median(conf):.2f}")

print("\n=== 2) 合成已知旋律 → MP3 → 听回来 ===")
MEL = [(60, 0, 1), (62, 1, 1), (64, 2, 1), (65, 3, 1), (67, 4, 1), (69, 5, 1), (71, 6, 1), (72, 7, 1),
       (72, 8, 2), (71, 10, 0.5), (69, 10.5, 0.5), (67, 11, 1), (64, 12, 2), (60, 14, 2), (55, 16, 1), (59, 17, 1)]
x, sr = synth(MEL)
mp3 = os.path.join(TMP, "known.mp3")
encode(x, sr, mp3, "mp3")
check("MP3 生成", os.path.getsize(mp3) > 10000, f"{os.path.getsize(mp3)//1024}KB")

y, ysr = audio_in.decode(mp3)
check("解码回来（时长一致）", abs(len(y) / ysr - len(x) / sr) < 0.15, f"{len(y)/ysr:.2f}s")

notes, info = audio_in.read_song(mp3, bpm=120.0)
pitch_ok = sum(1 for p, b, d in notes if any(p == ep and abs(b - eb) < 0.3 for ep, eb, _ in MEL))
check(f"听出的音高/起点命中素材（{pitch_ok}/{len(MEL)} 素材音，输出 {len(notes)} 音）",
      pitch_ok >= len(MEL) * 0.9, f"置信度均值 {info['conf_mean']}")
check("BPM 用给的 120（不被估计覆盖）", abs(info["bpm"] - 120) < 0.01, str(info["bpm"]))
check("音域正确（C4..C5 附近）", 50 <= info["lo"] <= 62 and 68 <= info["hi"] <= 76, f"{info['lo']}..{info['hi']}")
check("BPM 估计分支能跑（不给 bpm）", abs(audio_in.read_song(mp3)[1]["bpm"] - 120) <= 12,
      f"估出 {audio_in.read_song(mp3)[1]['bpm']}")

print("\n=== 3) WAV 同一条路 ===")
wav = os.path.join(TMP, "known.wav")
encode(x, sr, wav, "wav")
nw, iw = audio_in.read_song(wav, bpm=120.0)
okw = sum(1 for p, b, d in nw if any(p == ep and abs(b - eb) < 0.3 for ep, eb, _ in MEL))
check(f"WAV 也能听（命中 {okw}/{len(MEL)}）", okw >= len(MEL) * 0.9, f"输出 {len(nw)} 音")

print("\n=== 4) 接进谱面管线（score.parse_any 按扩展名分发）===")
import score as sm
sc = sm.parse_any(mp3, bpm=120.0)
check("parse_any 认出 AUDIO 格式", sc.fmt == "AUDIO", sc.fmt)
check("转成了 Note 列表（与 MIDI/简谱同形状）", len(sc.notes) == len(notes), f"{len(sc.notes)} 音")
check("带了信息型说明（不是当作错误）", any("音频" in w for w in sc.warnings), str(sc.warnings[:1])[:70])
tab, st = sm.to_score_table(sc, base_octave="auto", transpose=0)
check(f"能换算成按键（{st['playable']}/{st['notes']} 可弹）", st["playable"] > 0 and st["out_of_range"] == 0,
      f"音域 {st['lo']}..{st['hi']}")
import play
plan, acts, total = play.build_timeline(tab, play.argparse.Namespace(
    bpm=120.0, pad=False, from_measure=1, to_measure=10 ** 9, mode="hold", retrigger_ms=0.0,
    _fps=165.0, timing=None, late="shift", late_tol=0.05, min_rest=0.0))
check(f"能排成动作序列（{len(acts)} 个动作）", len(acts) > len(plan) and len(plan) == len(notes),
      f"{len(plan)} 音 → {len(acts)} 动作")

print("\n=== 5) 边界情况 ===")
sil = os.path.join(TMP, "silence.wav")
encode(np.zeros(sr * 2, dtype=np.float32), sr, sil, "wav")
try:
    audio_in.read_song(sil)
    check("全静音应明确报错", False, "居然没报错（应提示没听出音符）")
except Exception as e:
    check("全静音有明确报错", "音符" in str(e) or "音频" in str(e), f"{type(e).__name__}: {e}")
try:
    audio_in.decode(os.path.join(TMP, "nope.mp3"))
    check("不存在的文件应报错", False, "居然没报错")
except Exception as e:
    check("不存在的文件有明确报错", True, f"{type(e).__name__}")

import shutil
shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 58)
if FAIL:
    print(f"结果：失败 {FAIL} 项 / 共 {PASS + FAIL} 项")
    for n in FAILED:
        print(f"   ✗ {n}")
    sys.exit(1)
print(f"结果：全部通过 ✔（{PASS} 项）")
