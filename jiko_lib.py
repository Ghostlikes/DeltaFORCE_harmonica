#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容简谱匹配/保存工具。jiko 在线抓取已移除，本地曲谱与 DSL 仍可使用。"""
import difflib
import json
import os
import re
import sys
import unicodedata

BASE = 'https://jiko-official.top/delta'
HERE = os.path.dirname(os.path.abspath(__file__))
SONG_EXT = ('.jianpu', '.txt', '.mid', '.midi', '.json')



# ────────────────────────────────── 取数据 ──────────────────────────────────

def read_library(*args, **kwargs):
    raise RuntimeError("jiko 已限制第三方抓取，在线取数已停止；请用 songlib.py")


def parse_library(text):
    """把 globalThis.COMMUNITY_SONGS = [...] 抠成 Python list。"""
    if 'ACCESS DENIED' in text or '请通过官方站点' in text:
        raise RuntimeError('jiko 曲库已限制第三方抓取，停止解析提示占位数据；请访问官方网页')
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
    raise RuntimeError("jiko 在线曲库已移除；请用 python songlib.py --search 歌名")


# ────────────────────────────────── 匹配 ──────────────────────────────────

_JUNK = re.compile(r'[\s\u3000\-_·・.,，。、!！?？:：;；"\'“”‘’()（）\[\]【】《》'
                   r'<>/\\|~～+＋&＆#♯＃＝=*＊]+')


def normalize(s):
    """匹配用归一化：小写、去空格与各种标点/全角符号。"""
    return _JUNK.sub('', unicodedata.normalize('NFKC', str(s or '')).casefold())


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
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", s.split(".")[0]):
        s = "_" + s
    return (s or "未命名")[:150].rstrip(" .")


def to_jianpu_text(song):
    """转成 score.py 能直接吃的简谱文本（TITLE/BPM/KEY/METER 头 + 谱面正文）。"""
    lines = [f"TITLE={song.get('title', '')}",
             f"BPM={song.get('bpm', 90):g}",
             f"KEY={song.get('key', '1=C') or '1=C'}",
             f"METER={song.get('meter', '4/4') or '4/4'}"]
    meta = [x for x in (song.get('artist'), song.get('sharedBy')) if x]
    note = "// 来源: " + str(song.get("source_url") or BASE).replace("\n", " ").replace("\r", " ")
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


def _identity(text):
    # BPM/KEY/METER 也是谱面语义，不得把不同速度/调号的同音符谱误判为相同。
    return '\n'.join(ln.strip() for ln in text.splitlines()
                     if ln.strip() and not ln.strip().startswith('//')
                     and not re.match(r'^TITLE\s*=', ln.strip(), re.I))


def download(song, out_dir=None, overwrite=False, verbose=True):
    from pathlib import Path
    import tempfile
    directory = Path(out_dir or os.path.join(HERE, 'songs')).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_name(song.get('title'))
    new_text = to_jianpu_text(song)
    index = 0
    while True:
        suffix = '' if index == 0 else '(曲库)' if index == 1 else f'(曲库{index})'
        target = directory / (stem + suffix + '.jianpu')
        if target.exists() and not overwrite:
            with target.open(encoding='utf-8', errors='replace') as f:
                if _identity(f.read()) == _identity(new_text):
                    return str(target), '已存在（内容相同）'
            index += 1
            continue
        if overwrite:
            temp = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                                 dir=directory, delete=False) as f:
                    temp = f.name
                    f.write(new_text)
                os.replace(temp, target)
            finally:
                if temp and os.path.exists(temp):
                    os.unlink(temp)
        else:
            try:
                with target.open('x', encoding='utf-8', newline='\n') as f:
                    f.write(new_text)
            except FileExistsError:
                continue
        message = '已保存：' + str(target)
        if verbose:
            print('  ✔ ' + message)
        return str(target), message


def describe(song):
    """一行摘要，给人看的。"""
    return (f"{song.get('title', '?')}"
            + (f" · {song['artist']}" if song.get('artist') else '')
            + (f" · {song['bpm']:g}BPM" if isinstance(song.get('bpm'), (int, float)) else '')
            + (f" · {song.get('key', '')}" if song.get('key') else '')
            + (f" · 分享者 {song['sharedBy']}" if song.get('sharedBy') else ''))


# ────────────────────────────────── 命令行 ──────────────────────────────────

def _cli(argv):
    print("jiko 在线抓取已移除（站点限制第三方访问）。")
    print("请改用 python songlib.py --search 歌名；本地已有曲谱仍可播放。")
    print("官方网页：" + BASE)
    return 2


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
