#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公开曲谱检索：shallow 目录、visualizer 文本谱、JE 待补节奏谱。

不绕过登录、不抓取受限谱面。jiko 在线抓取及 shushu 重复首屏适配器已移除。
缓存与按需下载的谱面不随仓库分发。播放/导出仍使用原有解析器。
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import http.client
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import harmonica_config as hcfg
import jiko_lib

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, '_cache')
CACHE_TTL = 6 * 3600
STALE_TTL = 7 * 86400
UA = 'DeltaFORCE-harmonica/2.0 (public score search)'
SHALLOW_SITE = 'https://delta-test.shallow.ink/harmonica'
SHALLOW_API = 'https://delta-test-api.shallow.ink'
GITHUB_API = 'https://api.github.com'
VISUALIZER_REPO = 'ChiZhou6/harmonica-visualizer'
SOURCE_NAMES = {'shallow': 'DeltaForce 口琴曲库',
                'visualizer': 'harmonica-visualizer 文本谱', 'je': '自由神社 JE（待补节奏）'}
SOURCE_SITES = {'shallow': SHALLOW_SITE,
                'visualizer': f'https://github.com/{VISUALIZER_REPO}/tree/main/songs',
                'je': 'https://github.com/zytx121/je'}
SOURCE_DOWNLOADABLE = {'shallow': False, 'visualizer': True, 'je': False}
REMOVED_SOURCES = {
    'jiko': 'jiko 已限制第三方抓取，在线适配器已移除；请访问 https://jiko-official.top/delta/',
    'shushu': 'shushu 首屏目录与 shallow 重复，旧适配器已移除；请改用 --source shallow',
}


def http_get(url, timeout=12, tries=2, headers=None, data=None, verbose=False):
    """有限超时/重试/响应体；401/403/404/429 等客户端错误不重复请求。"""
    hdr = {'User-Agent': UA, 'Accept': 'application/json'}
    hdr.update(headers or {})
    body = json.dumps(data).encode('utf-8') if data is not None else None
    if body is not None:
        hdr.setdefault('Content-Type', 'application/json')
    last = None
    for attempt in range(max(1, tries)):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=hdr),
                                        timeout=timeout) as resp:
                raw = resp.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('响应超过 4 MiB，停止读取')
            return raw
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code < 500:
                hint = '（可能是匿名限流，请稍后重试或使用缓存）' if exc.code in (403, 429) else ''
                raise RuntimeError(f'HTTP {exc.code}{hint}: {url}') from exc
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            last = exc
        if attempt + 1 < max(1, tries):
            time.sleep(attempt + 1)
    raise RuntimeError(f'取数失败 {url}: {last}') from last


def _cache_read(name, ttl=CACHE_TTL):
    p = Path(CACHE_DIR) / name
    try:
        if ttl > 0 and time.time() - p.stat().st_mtime >= ttl:
            return None
        with p.open(encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_write(name, obj):
    """原子写入；只读缓存不应使成功的网络请求失败。"""
    temp = None
    try:
        Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=CACHE_DIR,
                                         suffix='.tmp', delete=False) as f:
            temp = f.name
            json.dump(obj, f, ensure_ascii=False)
        os.replace(temp, Path(CACHE_DIR) / name)
    except OSError:
        pass
    finally:
        if temp and os.path.exists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass


def _valid_catalog(items, source):
    return isinstance(items, list) and all(
        isinstance(s, dict) and s.get('src') == source and s.get('id')
        and isinstance(s.get('title'), str) and isinstance(s.get('artist'), str)
        and isinstance(s.get('chart'), bool) and isinstance(s.get('url'), str)
        for s in items)


def _cached_catalog(source, fetch, force=False, verbose=False, cache_name=None):
    name = cache_name or source + '_v2.json'
    cached = None if force else _cache_read(name)
    if cached is not None and _valid_catalog(cached, source):
        if verbose:
            print(f'  {source}: {len(cached)} 首（缓存）')
        return cached
    try:
        result = fetch()
        if not _valid_catalog(result, source):
            raise RuntimeError('曲库数据结构无效')
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        stale = _cache_read(name, STALE_TTL)
        if stale is not None and _valid_catalog(stale, source):
            if verbose:
                print(f'  [warn] {source} 联网失败，使用 7 天内旧缓存（可能过时）：{exc}')
            return stale
        raise RuntimeError(f'{source} 目录不可用：{exc}') from exc
    _cache_write(name, result)
    if verbose:
        print(f'  {source}: {len(result)} 首（在线）')
    return result


def _json(raw):
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('接口未返回有效 JSON（可能是错误页或访问限制）') from exc
    if not isinstance(obj, dict):
        raise RuntimeError('接口 JSON 不是对象')
    if 'code' in obj and obj['code'] != 0:
        raise RuntimeError(f"接口错误 code={obj['code']}: {str(obj.get('message') or '')[:120]}")
    return obj


def _shallow_token(force=False):
    cfg = hcfg.load()
    fp = cfg.get('device_id')
    if not fp:
        fp = str(uuid.uuid4())
        cfg['device_id'] = fp
        hcfg.save(cfg)
    cached = None if force else _cache_read('shallow_token.json', ttl=3600)
    if isinstance(cached, dict) and cached.get('fingerprint') == fp and cached.get('token'):
        return cached['token']
    obj = _json(http_get(SHALLOW_API + '/api/v1/auth/anonymous-token', data={'fingerprint': fp}))
    data = obj.get('data')
    tok = data.get('token') if isinstance(data, dict) else None
    if not isinstance(tok, str) or not tok:
        raise RuntimeError('匿名接口未返回令牌')
    _cache_write('shallow_token.json', dict(token=tok, fingerprint=fp))
    return tok


def _shallow_page(url, token):
    """匿名令牌过期只刷新一次；不尝试使用用户登录态。"""
    try:
        raw = http_get(url, headers={'X-Anonymous-Token': token})
    except RuntimeError as exc:
        if not isinstance(exc.__cause__, urllib.error.HTTPError) or exc.__cause__.code != 401:
            raise
        token = _shallow_token(force=True)
        return _json(http_get(url, headers={'X-Anonymous-Token': token})), token
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('目录接口未返回有效 JSON') from exc
    if isinstance(obj, dict) and obj.get('code') == 401:
        token = _shallow_token(force=True)
        raw = http_get(url, headers={'X-Anonymous-Token': token})
    return _json(raw), token


def _number(value):
    result = float(value or 0)
    if not math.isfinite(result) or result < 0:
        raise ValueError('曲库数值不是有限非负数')
    return result


def shallow_catalog(force=False, verbose=False):
    def fetch():
        token = _shallow_token(force=force)
        out, seen = [], set()
        for page in range(1, 101):
            obj, token = _shallow_page(
                f'{SHALLOW_API}/api/v1/df/harmonica/songs?page={page}&pageSize=100', token)
            data = obj.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('items'), list):
                raise RuntimeError('目录缺少 data.items')
            total = data.get('total')
            if type(total) is not int or total < 0:
                raise RuntimeError('目录缺少有效 total')
            items = data['items']
            for o in items:
                sid = o.get('songId') if isinstance(o, dict) else None
                if not isinstance(sid, str) or not sid or sid in seen:
                    raise RuntimeError('分页重复或曲目 ID 无效，未保存不完整目录')
                seen.add(sid)
                out.append(dict(src='shallow', id=sid, title=html.unescape(str(o.get('title') or '')),
                                artist=html.unescape(str(o.get('authorName') or '')),
                                bpm=round(_number(o.get('bpm')), 1), difficulty=o.get('difficulty') or '',
                                dur_s=round(_number(o.get('durationMs'))/1000, 1),
                                lo=o.get('pitchMin') or 0, hi=o.get('pitchMax') or 0,
                                chart=False, plays=_number(o.get('playCount')),
                                url=SHALLOW_SITE + '/' + urllib.parse.quote(sid, safe=''),
                                access='目录可检索；谱面请到原站查看'))
            if len(out) == total:
                return out
            if not items or len(out) > total:
                raise RuntimeError('分页不完整或总数变动，请刷新重试')
        raise RuntimeError('分页超过 100 页，未保存不完整目录')
    return _cached_catalog('shallow', fetch, force, verbose)


def visualizer_catalog(force=False, verbose=False):
    def fetch():
        tree = _json(http_get(f'{GITHUB_API}/repos/{VISUALIZER_REPO}/git/trees/main?recursive=1'))
        if tree.get('truncated') or not isinstance(tree.get('tree'), list):
            raise RuntimeError('GitHub 文件目录被截断或无效')
        out = []
        for entry in tree['tree']:
            path = entry.get('path', '')
            if entry.get('type') != 'blob' or not path.startswith('songs/') or not path.endswith(('.txt', '.jianpu')):
                continue
            quoted = urllib.parse.quote(path, safe='/')
            out.append(dict(src='visualizer', id=path, title=Path(path).stem, artist='', bpm=0,
                            chart=True, sha=entry['sha'],
                            url=f'https://github.com/{VISUALIZER_REPO}/blob/main/{quoted}',
                            access='公开文本谱；下载后解析校验'))
        if not out:
            raise RuntimeError('上游目录没有兼容的文本谱')
        return out
    return _cached_catalog('visualizer', fetch, force, verbose)


def je_search(query, limit=15, force=False, verbose=False):
    """标题检索；缺节奏的音高谱只给链接，不伪造等时值。"""
    query = query.strip()
    if not query:
        return []
    limit = min(50, max(1, limit))
    cache_key = hashlib.sha256((query + ':' + str(limit)).encode()).hexdigest()
    def fetch():
        words = query.replace('"', ' ').replace('\\', ' ').strip()
        params = urllib.parse.urlencode({'q': f'repo:zytx121/je is:issue in:title "{words}"',
                                         'per_page': limit})
        obj = _json(http_get(GITHUB_API + '/search/issues?' + params))
        if obj.get('incomplete_results') or not isinstance(obj.get('items'), list):
            raise RuntimeError('GitHub 搜索结果不完整或无效')
        return [dict(src='je', id=str(o['number']), title=o['title'], artist='', bpm=0,
                     chart=False, url=f"https://github.com/zytx121/je/issues/{int(o['number'])}",
                     access='音高文本，需人工核对并补充节奏') for o in obj['items']]
    return _cached_catalog('je', fetch, force, verbose, 'je_' + cache_key + '.json')


def catalog(source, force=False, verbose=False):
    if source in REMOVED_SOURCES:
        raise ValueError(REMOVED_SOURCES[source])
    if source == 'je':
        raise ValueError('JE 为按关键词检索来源，请用 --search 歌名 --source je')
    providers = {'shallow': shallow_catalog, 'visualizer': visualizer_catalog}
    if source not in providers:
        raise ValueError('未知曲库来源：' + str(source))
    return providers[source](force=force, verbose=verbose)


def catalogs(sources=None, force=False, verbose=False, query='', limit=15):
    selected = list(SOURCE_NAMES) if sources is None else list(dict.fromkeys(sources))
    for source in selected:
        if source not in SOURCE_NAMES:
            raise ValueError(REMOVED_SOURCES.get(source, '未知曲库来源：' + source))
    if not selected:
        return []
    def fetch(source):
        if source == 'je':
            return je_search(query, limit, force, verbose)
        return catalog(source, force=force, verbose=verbose)
    out, failures = [], []
    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        jobs = [(s, pool.submit(fetch, s)) for s in selected]
        for source, job in jobs:
            try:
                out.extend(job.result())
            except Exception as exc:
                failures.append(source)
                if verbose:
                    print(f'  [warn] {source} 失败：{exc}')
    if len(failures) == len(selected):
        raise RuntimeError('所有所选曲库请求失败，请检查网络或稍后重试（不是没有匹配曲目）')
    return out


def search(query, sources=None, limit=15, force=False, verbose=False):
    if not jiko_lib.normalize(query) or limit <= 0:
        return []
    pool = catalogs(sources, force, verbose, query=query, limit=limit)
    scored, seen = [], set()
    for s in pool:
        identity = (s['src'], s['id'])
        if identity in seen:
            continue
        seen.add(identity)
        sc = jiko_lib.match_score(s, query)
        if sc > 0:
            scored.append((sc, s))
    scored.sort(key=lambda x: (-x[0], not x[1]['chart'], -float(x[1].get('plays') or 0), x[1]['title']))
    return [s for _, s in scored[:limit]]


def describe(s):
    bits = [s['title']]
    if s.get('artist'):
        bits.append('— ' + s['artist'])
    bits.append('· ' + SOURCE_NAMES[s['src']])
    if s.get('bpm'):
        bits.append(f"· {s['bpm']:g}BPM")
    if s.get('difficulty'):
        bits.append('· ' + s['difficulty'])
    if s.get('dur_s'):
        seconds = int(s['dur_s'])
        bits.append(f'· {seconds//60}:{seconds%60:02d}')
    bits.append('· 可下载 ✔' if s['chart'] else '· ' + s.get('access', '仅提供原谱链接'))
    return ' '.join(bits)


def download(s, out_dir=None, overwrite=False, verbose=True):
    if s.get('src') != 'visualizer' or not s.get('chart'):
        return None, '此来源不提供自动下载；请查看原谱：' + str(s.get('url', ''))
    try:
        # 内容 SHA 校验；URL 固定在上游，不信任远端任意下载链接。
        sha = s.get('sha', '')
        if len(sha) != 40 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('曲谱 Git SHA 无效，请刷新目录')
        obj = _json(http_get(f'{GITHUB_API}/repos/{VISUALIZER_REPO}/git/blobs/{sha}'))
        if obj.get('encoding') != 'base64':
            raise ValueError('GitHub 返回了不支持的文件编码')
        blob = base64.b64decode(obj['content'])
        actual = hashlib.sha1(b'blob ' + str(len(blob)).encode() + b'\0' + blob).hexdigest()
        if actual != sha:
            raise ValueError('曲谱 Git 内容校验失败')
        text = blob.decode('utf-8-sig')
        if text.lstrip().startswith('<'):
            raise ValueError('响应是网页而不是曲谱')
        import score
        parsed = score.parse_any(str(s['id']), text=text)
        if not parsed.notes or not any(n.pitch is not None for n in parsed.notes):
            raise ValueError('谱面未解析出可演奏音符')
        parsed.title = str(s['title']).replace('\n', ' ').replace('\r', ' ')
        canonical = score.format_jianpu(parsed)
        back = score.parse_any('download.jianpu', text=canonical)
        before = [n for n in parsed.notes if n.pitch is not None]
        after = [n for n in back.notes if n.pitch is not None]
        if len(before) != len(after) or any(
                a.pitch != b.pitch or abs(a.start - b.start) > 0.002 or abs(a.dur - b.dur) > 0.002
                for a, b in zip(before, after)):
            raise ValueError('格式转换未通过音高/时值往返校验，未保存谱面')
        target_song = dict(title=parsed.title, bpm=parsed.bpm, key=parsed.key, meter=parsed.meter,
                           jianpu=jiko_lib._body_of(canonical), artist=VISUALIZER_REPO,
                           source_url=s['url'])
        return jiko_lib.download(target_song, out_dir, overwrite, verbose)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        return None, '下载/校验失败：' + str(exc)


def _cli(argv=None):
    ap = argparse.ArgumentParser(description='曲谱检索（shallow / visualizer / je）')
    ap.add_argument('--search', '-s', default='', help='歌名/作者关键词')
    ap.add_argument('--source', default='', choices=[''] + list(SOURCE_NAMES) + list(REMOVED_SOURCES))
    ap.add_argument('--list', action='store_true', help='列出来源及可枚举目录的实时数量')
    ap.add_argument('--refresh', action='store_true', help='忽略新鲜缓存；失败可退回 7 天内缓存')
    ap.add_argument('--limit', type=int, default=15)
    ap.add_argument('--download', action='store_true', help='下载排名最高的可下载结果（不演奏）')
    ap.add_argument('-o', '--out', default=os.path.join(HERE, 'songs'))
    a = ap.parse_args(argv)
    if a.limit < 1:
        ap.error('--limit 必须大于 0')
    sources = [a.source] if a.source else None
    if a.source in REMOVED_SOURCES:
        print(REMOVED_SOURCES[a.source])
        return 2
    if a.list or not a.search:
        failed = 0
        for source in sources or list(SOURCE_NAMES):
            if source == 'je':
                print(f'{SOURCE_NAMES[source]}：按关键词搜索，不枚举全库   {SOURCE_SITES[source]}')
                continue
            try:
                items = catalog(source, force=a.refresh, verbose=True)
                print(f'{SOURCE_NAMES[source]}：{len(items)} 首   {SOURCE_SITES[source]}')
            except (RuntimeError, ValueError) as exc:
                failed += 1
                print(f'{source} 失败：{exc}')
        return 1 if failed else 0
    try:
        hits = search(a.search, sources, a.limit, a.refresh, verbose=True)
    except (RuntimeError, ValueError) as exc:
        print(str(exc))
        return 2
    if not hits:
        print(f'可用来源未匹配到「{a.search}」；可缩短关键词或指定 --source 重试')
        return 1
    print(f'搜到 {len(hits)} 条：')
    for i, hit in enumerate(hits, 1):
        print(f'  {i}. {describe(hit)}\n     {hit["url"]}')
    if a.download:
        for hit in hits:
            if hit['chart']:
                path, message = download(hit, a.out)
                print(message or path)
                return 0 if path else 1
        print('结果仅提供原谱链接，没有可自动下载的兼容谱面')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
