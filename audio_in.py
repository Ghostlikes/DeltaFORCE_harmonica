#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_in.py — 把 MP3/WAV/OGG/FLAC 这类**音频**听成音符，接进现有的口琴谱管线。

和 midi_in.py 的位置一样：score.py 按扩展名分发到 read_song()，返回和 MIDI 相同的
(notes, info)，notes = [(midi, 起拍, 时值拍)]，后面 build_timeline / 按键映射全部复用。

依赖：PyAV（自带 FFmpeg 库，不需要单独装 ffmpeg/sox）+ numpy + scipy（本机都有）。

原理（单声部友好的「听旋律」）：
  1. 解码成单声道 22050Hz
  2. 带通 150~1500Hz（口琴/人声旋律所在区间，滤掉鼓和低音）
  3. 逐帧算 YIN 基频（NDF + 累积均值归一 + 绝对阈值 + 抛物线插值）
  4. 音量门限 + 音高置信度门限 → 只有真的在发声的帧才作数
  5. 相邻同音高的帧并成一个音；太短的（默认 <80ms）当噪声丢掉
  6. 按 BPM 量化到 1/16 网格，输出起拍/时值

实话实说：**单声部、旋律突出的音频（清唱、单乐器、口琴录音）效果好**；
编曲厚重的流行歌会跟着最突出的那件乐器走 —— 可以用 --mp3-fmin/--mp3-fmax 收窄区间。
"""
from __future__ import annotations

import math
import os
import numpy as np

SR = 22050              # 统一重采样到 22.05k，够覆盖到 1500Hz 以上
FMIN, FMAX = 120.0, 1500.0   # 检测区间：下限 120Hz 要盖住游戏最低可弹的 C3(131Hz)


# ────────────────────────────── 解码 ──────────────────────────────
def decode(path, sr=SR):
    """PyAV 解码任意音频 → 单声道 float32 numpy（归一化到 ±1）。"""
    import av
    chunks = []
    with av.open(path) as container:
        astreams = [s for s in container.streams if s.type == "audio"]
        if not astreams:
            raise ValueError(f"{os.path.basename(path)} 里没有音频流")
        stream = astreams[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sr)
        for frame in container.decode(stream):
            for rf in resampler.resample(frame):
                arr = rf.to_ndarray()                    # (1, n) int16
                chunks.append(arr.astype(np.float32).reshape(-1))
        for rf in resampler.resample(None):              # flush
            chunks.append(rf.to_ndarray().astype(np.float32).reshape(-1))
    if not chunks:
        raise ValueError(f"{os.path.basename(path)} 解不出音频数据")
    x = np.concatenate(chunks) / 32768.0
    return x, sr


def bandpass(x, sr, lo=FMIN, hi=FMAX, order=4):
    """4 阶巴特沃斯带通（滤掉鼓/低音/镲片）。"""
    from scipy.signal import butter, sosfiltfilt
    sos = butter(order, [lo / (sr / 2), min(hi, sr / 2 * 0.98) / (sr / 2)], btype="band", output="sos")
    return sosfiltfilt(sos, x)


# ────────────────────────────── 音高检测（YIN） ──────────────────────────────
def yin_f0(x, sr, frame=0.046, hop=0.010, tau_min=None, tau_max=None, threshold=0.15):
    """逐帧 YIN。返回 (f0 数组, 置信度数组, 帧中心时间数组)。用 FFT 算自相关，向量化分块。"""
    W = int(round(frame * sr))
    H = int(round(hop * sr))
    tau_min = max(2, int(sr / FMAX))
    tau_max = min(W - 2, int(sr / FMIN))
    n = len(x)
    if n < W:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    starts = np.arange(0, n - W, H)
    nf = len(starts)
    t = (starts + W / 2) / sr
    f0 = np.zeros(nf, dtype=np.float64)
    conf = np.zeros(nf, dtype=np.float64)
    nfft = 1 << int(math.ceil(math.log2(2 * W)))
    CH = 1500                                        # 分块，控制内存
    for c0 in range(0, nf, CH):
        c1 = min(nf, c0 + CH)
        idx = starts[c0:c1][:, None] + np.arange(W)[None, :]
        fr = x[idx]                                  # (m, W)
        fr = fr - fr.mean(axis=1, keepdims=True)
        spec = np.fft.rfft(fr, n=nfft, axis=1)
        acf = np.fft.irfft(spec * np.conj(spec), n=nfft, axis=1)[:, :tau_max + 1]
        # 差分函数 d(tau) = r(0) + r_tau(0) - 2 r(tau)
        # 后缀平方和必须沿**采样轴**反转（[:, ::-1]）；写成 fr[::-1,] 反的是帧序，结果是垃圾值
        power = np.cumsum((fr ** 2)[:, ::-1], axis=1)[:, ::-1]   # 后缀平方和
        d = power[:, 0:1] + power[:, :tau_max + 1] - 2 * acf
        d = np.maximum(d, 0.0)
        # 累积均值归一化（CMND）
        cmnd = np.ones_like(d)
        run = np.cumsum(d[:, 1:], axis=1)
        cmnd[:, 1:] = d[:, 1:] * np.arange(1, tau_max + 1)[None, :] / np.maximum(run, 1e-12)
        # 绝对阈值：第一个低于阈值之后的局部最小
        for i in range(cmnd.shape[0]):
            row = cmnd[i]
            lo = tau_min
            cands = np.where(row[lo:tau_max + 1] < threshold)[0]
            if len(cands) == 0:
                tau = int(lo + np.argmin(row[lo:tau_max + 1]))     # 没到阈值 → 取最小值
                c = float(max(0.0, 1.0 - row[tau]))
            else:
                j = lo + cands[0]
                # 往后找局部最小
                while j < tau_max and row[j + 1] < row[j]:
                    j += 1
                tau = int(j)
                c = float(max(0.0, 1.0 - row[tau]))
            # 抛物线插值
            if tau_min < tau < tau_max:
                a, b, cc = row[tau - 1], row[tau], row[tau + 1]
                den = 2 * (2 * b - a - cc)
                off = (cc - a) / den if abs(den) > 1e-12 else 0.0
                off = float(np.clip(off, -0.5, 0.5))
            else:
                off = 0.0
            tau_f = tau + off
            f0[c0 + i] = sr / tau_f if tau_f > 0 else 0.0
            conf[c0 + i] = c
    return f0, conf, t


# ────────────────────────────── 主入口 ──────────────────────────────
def read_song(path, bpm=None, fmin=FMIN, fmax=FMAX, min_dur=0.08, max_gap=0.05,
              conf_min=0.55, rms_db=-42.0, key=None, verbose=False, **_kw):
    """音频 → (notes, info)，notes = [(midi, 起拍, 时值拍)]，与 midi_in.read_song 同形状。"""
    x, sr = decode(path)
    dur_s = len(x) / sr
    if verbose:
        print(f"  解码：{os.path.basename(path)} → {dur_s:.1f}s / {sr}Hz / {len(x)} 采样")
    xb = bandpass(x, sr, fmin, fmax)
    f0, conf, t = yin_f0(xb, sr, tau_min=int(sr / fmax), tau_max=int(sr / fmin))
    if not len(f0):
        raise ValueError("音频太短，听不出音符")
    # 音量门限（相对满刻度）
    hop = float(t[1] - t[0]) if len(t) > 1 else 0.01
    W = int(round(0.046 * sr))
    starts = (t * sr - W / 2).astype(int)
    starts = np.clip(starts, 0, max(0, len(x) - W))
    idx = starts[:, None] + np.arange(W)[None, :]
    rms = np.sqrt((x[idx] ** 2).mean(axis=1))
    gate = rms > 10 ** (rms_db / 20)
    voiced = gate & (conf >= conf_min) & (f0 >= fmin * 0.98) & (f0 <= fmax * 1.02)

    # 帧 → 音符（同音高的连续帧并起来）
    segs, cur = [], None
    for i in range(len(f0)):
        if not voiced[i]:
            if cur is not None:
                segs.append(cur); cur = None
            continue
        m = 69 + 12 * math.log2(f0[i] / 440.0)
        if cur is None:
            cur = dict(start=t[i] - hop / 2, end=t[i] + hop / 2, ms=[m], devs=[abs(m - round(m))])
        else:
            centre = float(np.median(cur["ms"]))
            if abs(m - centre) <= 0.6:                 # 同一个音
                cur["end"] = t[i] + hop / 2; cur["ms"].append(m); cur["devs"].append(abs(m - round(m)))
            else:
                segs.append(cur)
                cur = dict(start=t[i] - hop / 2, end=t[i] + hop / 2, ms=[m], devs=[abs(m - round(m))])
    if cur is not None:
        segs.append(cur)

    # 粘连：间隔很小又同音高的段合并（颤音/换气）
    merged = []
    for s in segs:
        if merged and abs(round(float(np.median(merged[-1]["ms"]))) - round(float(np.median(s["ms"])))) == 0 \
           and s["start"] - merged[-1]["end"] <= max_gap:
            merged[-1]["end"] = s["end"]; merged[-1]["ms"] += s["ms"]; merged[-1]["devs"] += s["devs"]
        else:
            merged.append(s)
    # 丢太短的
    notes_raw = [s for s in merged if s["end"] - s["start"] >= min_dur]
    dropped = len(merged) - len(notes_raw)

    # BPM：给了就用，没给就从起音间隔估
    est_bpm = None
    if bpm is None:
        ons = np.array([s["start"] for s in notes_raw]) if notes_raw else np.zeros(0)
        if len(ons) > 8:
            d = np.diff(ons); d = d[(d > 0.15) & (d < 2.0)]
            if len(d):
                grid = np.arange(60.0 / 200, 60.0 / 60, 0.002)       # 60~200 BPM 的 1/4 拍间隔
                best, bestc = 120.0, -1
                for g in grid:
                    r = d / g; q = np.abs(r - np.round(r))
                    c = float((q < 0.12).mean())
                    if c > bestc: bestc, best = c, 60.0 / g
                est_bpm = round(best)
    bpm_use = float(bpm or est_bpm or 120.0)

    # 量化到 1/16 网格
    step = 60.0 / bpm_use / 4.0
    notes = []
    for s in notes_raw:
        p = int(round(float(np.median(s["ms"]))))
        b0 = round((s["start"] / (60.0 / bpm_use)) / 0.25) * 0.25          # 起拍
        b1 = round((max(s["end"], s["start"] + 0.5 * step) / (60.0 / bpm_use)) / 0.25) * 0.25
        d = max(0.25, b1 - b0)
        notes.append((p, float(b0), float(d)))
    notes.sort(key=lambda n: n[1])
    # 修重叠（前一个音盖住后一个音的起点）
    fixed = []
    for i, (p, b, d) in enumerate(notes):
        if fixed and b < fixed[-1][1] + fixed[-1][2]:
            pb, pbb, pdd = fixed[-1]
            fixed[-1] = (pb, pbb, max(0.25, b - pbb))
        fixed.append((p, b, d))
    notes = fixed

    if not notes:
        raise ValueError(
            f"{os.path.basename(path)} 里没听出音符（{dur_s:.1f}s，有声帧 {int(voiced.sum())}/{len(f0)}，"
            f"平均置信度 {float(conf.mean()):.2f}）。可能是：整段静音/纯打击乐、音高都在 "
            f"{fmin:g}~{fmax:g}Hz 之外、或者门限太严 —— 可以试 --mp3-conf 0.4、"
            f"--mp3-fmin/--mp3-fmax 放宽区间、--mp3-min-dur 调小")

    # 粗略猜个调（音级直方图 vs 大/小调模板）——只用于写进注释，不影响播放
    hist = np.zeros(12)
    for p, _, d in notes:
        hist[p % 12] += d
    MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    names = ["C", "bD", "D", "bE", "E", "F", "bG", "G", "bA", "A", "bB", "B"]
    best = (None, -9)
    if hist.sum() > 0:
        h = hist / hist.sum()
        for r in range(12):
            for nm, prof in (("", MAJ), ("m", MIN)):
                c = float(np.corrcoef(np.roll(prof, r), h)[0, 1])
                if c > best[1]: best = (f"{names[r]}{nm}", c)
    key_guess = key or best[0]

    info = dict(bpm=bpm_use, bpm_estimated=est_bpm, key=key_guess, key_corr=round(best[1], 3),
                seconds=dur_s, frames=len(f0), voiced=int(voiced.sum()),
                notes=len(notes), dropped_short=dropped,
                conf_mean=round(float(conf[voiced].mean()), 3) if voiced.any() else 0.0,
                lo=int(min((n[0] for n in notes), default=0)), hi=int(max((n[0] for n in notes), default=0)),
                format=os.path.splitext(path)[1].lstrip(".").upper())
    return notes, info
