#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jiko-official.top/delta 曲库直连：按歌名搜索 → 下载成 songs/ 里可直接弹奏的简谱。

站点取数原理（实测 2026-09，站点版本 v3.1.0）：
    页面 https://jiko-official.top/delta/ 里引了一行
        <script src="./data/community-songs.js?v=3.1.0">
    该文件是单行 JS：  globalThis.COMMUNITY_SONGS = [ {...}, {...} ]
    每条记录字段： title / artist / sharedBy / key / meter / bpm / jianpu / source / remixCode
所以「按歌名搜索」不需要账号、也不用抓 HTML：把这份 JSON 拉下来本地匹配即可。
（站点另有 ./api/public-library/songs，但那条走的是登录态 authRequest，公开检索用不上。）

命令行自测：
    python jiko_lib.py --list                     列出曲库
    python jiko_lib.py --search 天空之城            只搜索，看匹配排序
    python jiko_lib.py --get 天空之城 -o songs      搜到就下载到 songs/
"""
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = 'https://jiko-official.top/delta'
LIB_URL = BASE + '/data/community-songs.js'
UA = 'harmonica-autoplay/1.0 (+local; score-library fetch)'
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '_cache', 'community-songs.js')
CACHE_TTL = 6 * 3600          # 曲库缓存 6 小时，之后自动重拉
SONG_EXT = ('.jianpu', '.txt', '.mid', '.midi', '.json')

_LIB = None                   # 进程内缓存：(songs, 来源说明)


# ────────────────────────────────── 取数据 ──────────────────────────────────

def http_get(url, timeout=30, tries=3, verbose=True):
    """带重试的 GET。失败抛 RuntimeError（消息里带人话原因，便于交互模式直接打印）。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA,
                                                       'Accept': 'application/json,text/javascript,*/*'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:            # URLError / HTTPError / timeout / ssl
            last = e
            if verbose and i + 1 < tries:
                print(f"  连接失败（第 {i + 1}/{tries} 次）：{type(e).__name__}: {e}，重试…")
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def read_library(force=False, offline=False, ttl=CACHE_TTL, verbose=True):
    """拿曲库原文：优先本地缓存（6 小时内），否则联网，联网失败再退回旧缓存。"""
    if not force and os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < ttl:
        return open(CACHE, encoding='utf-8', errors='replace').read(), '本地缓存'
    if offline:
        if os.path.exists(CACHE):
            return open(CACHE, encoding='utf-8', errors='replace').read(), '本地缓存（离线）'
        raise RuntimeError('离线模式且没有本地缓存')
    try:
        text = http_get(LIB_URL, verbose=verbose)
    except RuntimeError as e:
        if os.path.exists(CACHE):
            if verbose:
                print(f"  联网取曲库失败（{e}），改用本地旧缓存")
            return open(CACHE, encoding='utf-8', errors='replace').read(), '本地旧缓存'
        raise
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return text, '在线拉取'


def parse_library(text):
    """把 globalThis.COMMUNITY_SONGS = [...] 抠成 Python list。"""
    i, j = text.find('['), text.rfind(']')
    if i < 0 or j < i:
        raise RuntimeError('曲库文件里没有找到 JSON 数组（站点结构可能变了）')
    try:
        songs = json.loads(text[i:j + 1])
    except Exception as e:
        raise RuntimeError(f'曲库 JSON 解析失败：{e}')
    if not isinstance(songs, list) or not songs:
        raise RuntimeError('曲库内容为空')
    return [s for s in songs if isinstance(s, dict) and s.get('jianpu')]


def load_songs(force=False, offline=False, verbose=True):
    """→ (list[dict], 来源说明)。同进程复用。"""
    global _LIB
    if _LIB is not None and not force:
        return _LIB
    text, src = read_library(force=force, offline=offline, verbose=verbose)
    songs = parse_library(text)
    _LIB = (songs, src)
    if verbose:
        print(f"  jiko 曲库：{len(songs)} 首（{src}）")
    return _LIB


# ────────────────────────────────── 匹配 ──────────────────────────────────

_JUNK = re.compile(r'[\s\u3000\-_·・.,，。、!！?？:：;；"\'“”‘’()（）\[\]【】《》'
                   r'<>/\\|~～+＋&＆#♯＃＝=*＊]+')


def normalize(s):
    """匹配用归一化：小写、去空格与各种标点/全角符号。"""
    return _JUNK.sub('', str(s or '').lower())


def match_score(song, query):
    """越大越像；0 = 不匹配。title 权重最高，artist/sharedBy 次之，最后给模糊相似度兜底。"""
    q = normalize(query)
    if not q:
        return 0
    title = normalize(song.get('title'))
    artist = normalize(song.get('artist'))
    shared = normalize(song.get('sharedBy'))
    best = 0
    if title == q:
        best = 1000
    elif title.startswith(q):
        best = 850 - min(150, len(title) - len(q))
    elif q in title:
        best = 700 - min(150, len(title) - len(q))
    elif title and title in q:
        best = 650
    if artist and q in artist:
        best = max(best, 420)
    if shared and q in shared:
        best = max(best, 300)
    ratio = difflib.SequenceMatcher(None, q, title).ratio()
    if ratio >= 0.55:
        best = max(best, int(ratio * 600))
    return best


def search(query, songs=None, limit=10):
    """→ [(score, song), …] 按相似度降序。"""
    if songs is None:
        songs = load_songs(verbose=False)[0]
    hits = []
    for s in songs:
        sc = match_score(s, query)
        if sc > 0:
            hits.append((sc, s))
    hits.sort(key=lambda x: (-x[0], len(str(x[1].get('title', '')))))
    return hits[:limit]


def suggest(query, songs=None, limit=3):
    """没搜到时给几个「最接近的名字」，避免让人干瞪眼。"""
    if songs is None:
        songs = load_songs(verbose=False)[0]
    q = normalize(query)
    scored = []
    for s in songs:
        t = normalize(s.get('title'))
        scored.append((difflib.SequenceMatcher(None, q, t).ratio(), s))
    scored.sort(key=lambda x: -x[0])
    return [s for r, s in scored[:limit] if r > 0.2]


# ────────────────────────────────── 落盘 ──────────────────────────────────

def safe_name(name):
    """Windows 非法文件名字符 → 下划线（与 extract_songlib.py 同一套规则）。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', str(name or '')).strip(' .')
    return s or '未命名'


def to_jianpu_text(song):
    """转成 score.py 能直接吃的简谱文本（TITLE/BPM/KEY/METER 头 + 谱面正文）。"""
    lines = [f"TITLE={song.get('title', '')}",
             f"BPM={song.get('bpm', 90):g}",
             f"KEY={song.get('key', '1=C') or '1=C'}",
             f"METER={song.get('meter', '4/4') or '4/4'}"]
    meta = [x for x in (song.get('artist'), song.get('sharedBy')) if x]
    note = f"// 来源: {BASE} 公共曲库"
    if meta:
        note += ' · ' + ' · '.join(meta)
    if song.get('remixCode'):
        note += f" · remixCode={song['remixCode']}"
    lines += [note, '', str(song.get('jianpu', '')).rstrip(), '']
    return '\n'.join(lines)


def _body_of(text):
    """只比较谱面正文（忽略来源注释），用来判断「磁盘上那份和曲库这份是否同一份」。"""
    keep = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith('//'):
            continue
        if re.match(r'^(TITLE|BPM|KEY|METER)\s*=', s, re.I):
            continue
        keep.append(s)
    return '\n'.join(keep)


def download(song, out_dir=None, overwrite=False, verbose=True):
    """把一首曲库曲子写进曲谱文件夹 → (路径, 说明)。

    绝不静默覆盖：同名文件内容不同时另存为「曲名(曲库).jianpu」，
    只有 overwrite=True（--force）才会覆盖原文件。
    """
    out_dir = os.path.abspath(os.path.expanduser(str(out_dir or os.path.join(HERE, 'songs'))))
    os.makedirs(out_dir, exist_ok=True)
    title = str(song.get('title') or '未命名').strip()
    stem = safe_name(title)
    new_text = to_jianpu_text(song)
    target = os.path.join(out_dir, stem + '.jianpu')
    note = ''
    if os.path.exists(target) and not overwrite:
        old = open(target, encoding='utf-8', errors='replace').read()
        if _body_of(old) == _body_of(new_text):
            if verbose:
                print(f"  ✔ {os.path.basename(target)} 已存在且内容相同，直接用（不重复下载）")
            return target, '已存在（内容相同）'
        n, alt = 2, os.path.join(out_dir, f'{stem}(曲库).jianpu')
        while os.path.exists(alt):
            if _body_of(open(alt, encoding='utf-8', errors='replace').read()) == _body_of(new_text):
                if verbose:
                    print(f"  ✔ {os.path.basename(alt)} 已存在且内容相同，直接用")
                return alt, '已存在（内容相同）'
            alt = os.path.join(out_dir, f'{stem}(曲库{n}).jianpu')
            n += 1
        note = f'{os.path.basename(target)} 内容不同（本地那份不是曲库版），另存为 {os.path.basename(alt)}'
        target = alt
    elif os.path.exists(target) and overwrite:
        note = f'已按 --force 覆盖 {os.path.basename(target)}'
    with open(target, 'w', encoding='utf-8', newline='\n') as f:
        f.write(new_text)
    if verbose:
        print(f"  ✔ 已保存：{target}" + (f"（{note}）" if note else ''))
    return target, note


def describe(song):
    """一行摘要，给人看的。"""
    return (f"{song.get('title', '?')}"
            + (f" · {song['artist']}" if song.get('artist') else '')
            + (f" · {song['bpm']:g}BPM" if isinstance(song.get('bpm'), (int, float)) else '')
            + (f" · {song.get('key', '')}" if song.get('key') else '')
            + (f" · 分享者 {song['sharedBy']}" if song.get('sharedBy') else ''))


# ────────────────────────────────── 命令行 ──────────────────────────────────

def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(description='jiko 曲库搜索/下载（不弹奏）')
    ap.add_argument('--list', action='store_true', help='列出曲库全部曲目')
    ap.add_argument('--search', default='', metavar='歌名', help='只搜索并显示匹配排序')
    ap.add_argument('--get', default='', metavar='歌名', help='搜索并下载匹配到的曲子')
    ap.add_argument('-o', '--out', default='', help='下载目录（默认 songs/）')
    ap.add_argument('--force', action='store_true', help='覆盖同名文件')
    ap.add_argument('--refresh', action='store_true', help='忽略缓存，重新联网拉曲库')
    a = ap.parse_args(argv)
    songs, src = load_songs(force=a.refresh)
    if a.list:
        print(f"jiko 曲库 {len(songs)} 首（{src}）：")
        for i, s in enumerate(sorted(songs, key=lambda x: str(x.get('title'))), 1):
            print(f"  {i:3d}. {describe(s)}")
        return 0
    if a.search:
        hits = search(a.search, songs, limit=15)
        if not hits:
            print(f"没搜到「{a.search}」。相近的：")
            for s in suggest(a.search, songs):
                print(f"  · {describe(s)}")
            return 1
        print(f"「{a.search}」匹配到 {len(hits)} 条：")
        for i, (sc, s) in enumerate(hits, 1):
            print(f"  {i:2d}. [{sc:4d}] {describe(s)}")
        return 0
    if a.get:
        hits = search(a.get, songs, limit=10)
        if not hits:
            print(f"没搜到「{a.get}」，换关键词试试（python jiko_lib.py --search 关键词）")
            return 1
        sc, song = hits[0]
        print(f"选中：{describe(song)}（匹配度 {sc}）")
        download(song, out_dir=a.out or None, overwrite=a.force)
        return 0
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
