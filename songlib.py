#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""songlib.py — 多源口琴曲库：按歌名跨站搜索，能下的直接下到 songs/。

三个曲源（都只用各家**公开**接口，不绕过登录、不伪造凭证）：

| 来源 | 站点 | 目录 | 谱面本体 |
|---|---|---|---|
| `jiko` | https://jiko-official.top/delta | 公共曲库 JSON（116 首） | **可下载**（公共文件） |
| `shushu` | https://shushu.fan/fun/harmonica | 页面 SSR 载荷（195 首） | 需登录 → 给直达链接 |
| `shallow` | https://delta-test.shallow.ink/harmonica | 公开 API（196 首，匿名令牌） | 不在公开接口 → 给直达链接 |

shallow 用的是它自己的公开流程：`POST /api/v1/auth/anonymous-token` 带一个设备指纹
（随机 uuid，存在 ~/.harmonica_config.json 里），拿到 `anon_…` 令牌后带 `X-Anonymous-Token` 调
`/api/v1/df/harmonica/songs`。这是它给网页端用的同一套机制，没有绕过任何鉴权。

命令行自测：
    python songlib.py --list                         列出三个源
    python songlib.py --search 天空之城                跨源搜索
    python songlib.py --search 处处吻 --source shallow 只搜某一源
    python songlib.py --refresh                      重建目录缓存（_cache/）
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import jiko_lib                                              # jiko 曲源（已实现取数/下载）
try:
    import harmonica_config as hcfg                          # 复用同一个配置文件存设备指纹
except Exception:                                            # pragma: no cover
    hcfg = None

CACHE_DIR = os.path.join(HERE, '_cache')
CACHE_TTL = 6 * 3600
UA = 'harmonica-autoplay/1.0 (+local; song-library search)'

SHUSHU_BASE = 'https://shushu.fan'
SHUSHU_PAGE = SHUSHU_BASE + '/fun/harmonica'
SHALLOW_SITE = 'https://delta-test.shallow.ink/harmonica'
SHALLOW_API = 'https://delta-test-api.shallow.ink'

SOURCE_NAMES = {'jiko': 'jiko 公共曲库', 'shushu': 'shushu.fan 口琴曲谱', 'shallow': 'DeltaForce 口琴曲库'}
SOURCE_SITES = {'jiko': 'https://jiko-official.top/delta', 'shushu': SHUSHU_PAGE, 'shallow': SHALLOW_SITE}
SOURCE_DOWNLOADABLE = {'jiko': True, 'shushu': False, 'shallow': False}


# ───────────────────────────── 通用小工具 ─────────────────────────────

def http_get(url, timeout=30, tries=3, headers=None, data=None, verbose=False):
    """GET/POST 拿 bytes；带重试。"""
    hdr = {'User-Agent': UA, 'Accept': '*/*'}
    hdr.update(headers or {})
    body = json.dumps(data).encode() if data is not None else None
    if body is not None:
        hdr.setdefault('Content-Type', 'application/json')
    last = None
    for i in range(max(1, tries)):
        try:
            req = urllib.request.Request(url, data=body, headers=hdr)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                                # 网络抖动重试
            last = e
            if i + 1 < tries:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'取数失败 {url}: {last}')


def _rsc_text(html: str) -> str:
    """把 Next.js 的 RSC 载荷（self.__next_f.push([1,"…"])）拼回可读文本。

    只还原 JS 转义，**不要**用 unicode_escape —— 那会把 UTF-8 中文按 latin-1 解成乱码。
    """
    segs = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\s*\]\)', html)
    blob = ''.join(segs)
    m = {'n': '\n', 'r': '\r', 't': '\t', '"': '"', '\\': '\\', '/': '/', "'": "'"}
    return re.sub(r'\\(u[0-9a-fA-F]{4}|.)',
                  lambda x: chr(int(x.group(1)[1:], 16)) if x.group(1).startswith('u')
                  else m.get(x.group(1), x.group(1)), blob)


def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def _cache_read(name, ttl=CACHE_TTL):
    p = _cache_path(name)
    if os.path.isfile(p) and (ttl <= 0 or time.time() - os.path.getmtime(p) < ttl):
        try:
            return json.load(open(p, encoding='utf-8'))
        except Exception:
            return None
    return None


def _cache_write(name, obj):
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump(obj, open(_cache_path(name), 'w', encoding='utf-8'), ensure_ascii=False)


# ───────────────────────────── 曲源：jiko ─────────────────────────────

def jiko_catalog(force=False, verbose=False):
    songs, _src = jiko_lib.load_songs(force=force, verbose=verbose) or ([], '')
    return [dict(src='jiko', id=s.get('remixCode') or s.get('title'), title=s.get('title') or '',
                 artist=s.get('artist') or s.get('sharedBy') or '', bpm=s.get('bpm') or 0,
                 difficulty='', dur_s=0, lo=0, hi=0, nps=0, chart=True,
                 url=jiko_lib.BASE, raw=s) for s in songs]


# ───────────────────────────── 曲源：shushu ─────────────────────────────

def shushu_catalog(force=False, verbose=False):
    """shushu.fan 的口琴曲谱目录：页面把整库塞在 SSR 的 RSC 载荷里（195 首）。"""
    cached = None if force else _cache_read('shushu.json')
    if cached:
        return cached
    html = http_get(SHUSHU_PAGE, headers={'Accept': 'text/html'}, verbose=verbose).decode('utf-8', 'replace')
    txt = _rsc_text(html)
    out = []
    for m in re.finditer(r'\{"songId":"([0-9a-f]{32})"[^{}]*\}', txt):
        try:
            o = json.loads(m.group(0))
        except Exception:
            continue
        out.append(dict(src='shushu', id=o['songId'], title=o.get('title') or '',
                        artist=o.get('authorName') or '', bpm=round(float(o.get('bpm') or 0), 1),
                        difficulty=o.get('difficulty') or '',
                        dur_s=round((o.get('durationMs') or 0) / 1000.0, 1),
                        lo=o.get('pitchMin') or 0, hi=o.get('pitchMax') or 0,
                        nps=round(float(o.get('notesPerSecond') or 0), 2),
                        likes=o.get('likeCount') or 0, chart=False,
                        url=f"{SHUSHU_PAGE}/{o['songId']}", raw=o))
    dedup = {s['id']: s for s in out}
    out = sorted(dedup.values(), key=lambda s: (-(s.get('likes') or 0), s['title']))
    if out:
        _cache_write('shushu.json', out)
    return out


# ───────────────────────────── 曲源：shallow ─────────────────────────────

def _shallow_token(force=False):
    """shallow 的匿名令牌（其网页端用的同一套公开机制：设备指纹换令牌）。"""
    cfg = hcfg.load() if hcfg else {}
    fp = cfg.get('device_id')
    if not fp:
        fp = str(uuid.uuid4())
        if hcfg:
            cfg['device_id'] = fp
            hcfg.save(cfg)
    cached = None if force else _cache_read('shallow_token.json', ttl=3600)
    if cached and cached.get('fingerprint') == fp:
        return cached.get('token')
    data = http_get(SHALLOW_API + '/api/v1/auth/anonymous-token', data={'fingerprint': fp},
                    headers={'Origin': SHALLOW_SITE.rsplit('/harmonica', 1)[0],
                             'Referer': SHALLOW_SITE}).decode('utf-8', 'replace')
    tok = (json.loads(data).get('data') or {}).get('token')
    if not tok:
        raise RuntimeError(f'拿不到匿名令牌：{data[:200]}')
    _cache_write('shallow_token.json', dict(token=tok, fingerprint=fp))
    return tok


def shallow_catalog(force=False, verbose=False):
    cached = None if force else _cache_read('shallow.json')
    if cached:
        return cached
    tok = _shallow_token(force=force)
    hdr = {'X-Anonymous-Token': tok, 'Origin': SHALLOW_SITE.rsplit('/harmonica', 1)[0], 'Referer': SHALLOW_SITE}
    out, page, size = [], 1, 100
    while True:
        url = f'{SHALLOW_API}/api/v1/df/harmonica/songs?page={page}&pageSize={size}'
        d = json.loads(http_get(url, headers=hdr, verbose=verbose).decode('utf-8', 'replace'))
        data = d.get('data') or {}
        items = data.get('items') or []
        for o in items:
            out.append(dict(src='shallow', id=o.get('songId'), title=o.get('title') or '',
                            artist=o.get('authorName') or '', bpm=round(float(o.get('bpm') or 0), 1),
                            difficulty=o.get('difficulty') or '',
                            dur_s=round((o.get('durationMs') or 0) / 1000.0, 1),
                            lo=o.get('pitchMin') or 0, hi=o.get('pitchMax') or 0,
                            nps=round(float(o.get('notesPerSecond') or 0), 2),
                            plays=o.get('playCount') or 0, chart=False,
                            url=f"{SHALLOW_SITE}/{o.get('songId')}", raw=o))
        total = data.get('total') or 0
        if not items or len(out) >= total:
            break
        page += 1
        if page > 20:                                        # 防御：别无限翻页
            break
    if out:
        _cache_write('shallow.json', out)
    return out


# ───────────────────────────── 统一搜索 ─────────────────────────────

def catalog(source, force=False, verbose=False):
    return {'jiko': jiko_catalog, 'shushu': shushu_catalog, 'shallow': shallow_catalog}[source](force=force, verbose=verbose)


def catalogs(sources=None, force=False, verbose=False):
    out = []
    for s in (sources or list(SOURCE_NAMES)):
        try:
            out += catalog(s, force=force, verbose=verbose)
        except Exception as e:
            if verbose:
                print(f'  [warn] {s} 目录取不到：{e}')
    return out


def search(query, sources=None, limit=15, force=False, verbose=False):
    """跨源按歌名/作者搜，按匹配度排序。返回列表（含来源、难度、音域、时长、能否下载）。"""
    pool = catalogs(sources=sources, force=force, verbose=verbose)
    scored = []
    for s in pool:
        sc = jiko_lib.match_score({'title': s['title'], 'artist': s['artist']}, query)
        if sc > 0:
            scored.append((sc, s))
    # 同分时：能下载的优先，其次热度高的
    scored.sort(key=lambda x: (-x[0], not x[1]['chart'], -(x[1].get('likes') or x[1].get('plays') or 0)))
    return [s for _sc, s in scored[:limit]]


def describe(s):
    bits = [f"{s['title']}"]
    if s.get('artist'):
        bits.append(f"— {s['artist']}")
    bits.append(f"· {SOURCE_NAMES[s['src']]}")
    if s.get('bpm'):
        bits.append(f"· {s['bpm']:g}BPM")
    if s.get('difficulty'):
        bits.append(f"· {s['difficulty']}")
    if s.get('dur_s'):
        bits.append(f"· {int(s['dur_s'])//60}:{int(s['dur_s'])%60:02d}")
    if s.get('lo') and s.get('hi'):
        bits.append(f"· 音域 {s['lo']}..{s['hi']}")
    bits.append('· 可下载 ✔' if s['chart'] else '· 需登录，只能给链接')
    return ' '.join(bits)


def download(s, out_dir=None, overwrite=False, verbose=True):
    """能下的下到 songs/；不能在公开接口拿到的，返回 (None, 原因)。"""
    if s['src'] == 'jiko':
        return jiko_lib.download(s['raw'], out_dir=out_dir, overwrite=overwrite, verbose=verbose)
    return None, (f"{SOURCE_NAMES[s['src']]} 的谱面不在公开接口里（需登录 / 是站内媒体文件），"
                  f"已给你直达链接：{s['url']}")


# ───────────────────────────── CLI ─────────────────────────────

def _cli(argv=None):
    ap = argparse.ArgumentParser(description='多源口琴曲库搜索（jiko / shushu / shallow）')
    ap.add_argument('--search', '-s', default='', help='按歌名或作者搜索')
    ap.add_argument('--source', default='', help='限定来源：jiko / shushu / shallow（默认全部）')
    ap.add_argument('--list', action='store_true', help='列出各源曲目数量与前几首')
    ap.add_argument('--refresh', action='store_true', help='强制重建目录缓存')
    ap.add_argument('--limit', type=int, default=15)
    ap.add_argument('--download', action='store_true', help='搜到可下载的就下到 songs/')
    ap.add_argument('-o', '--out', default=os.path.join(HERE, 'songs'), help='下载目录')
    a = ap.parse_args(argv)
    srcs = [a.source] if a.source else None

    if a.list or not a.search:
        for s in (srcs or list(SOURCE_NAMES)):
            try:
                items = catalog(s, force=a.refresh, verbose=True)
                print(f'{SOURCE_NAMES[s]:<24} {len(items):>4} 首   {SOURCE_SITES[s]}')
                for it in items[:3]:
                    print('     ', describe(it))
            except Exception as e:
                print(f'{SOURCE_NAMES[s]:<24} 取不到：{e}')
        return 0

    hits = search(a.search, sources=srcs, limit=a.limit, force=a.refresh, verbose=True)
    if not hits:
        print(f'三个源都没搜到「{a.search}」')
        return 1
    print(f'搜到 {len(hits)} 条：')
    for i, h in enumerate(hits, 1):
        print(f'  {i:>2}. {describe(h)}')
    if a.download:
        for h in hits:
            if h['chart']:
                path, msg = download(h, out_dir=a.out)
                print(f"  下载：{msg}")
                return 0 if path else 1
        print('  搜到的都不可下载，去链接里找吧')
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
