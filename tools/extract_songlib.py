#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 jiko-official.top/delta 的前端 app.js 里抽出内置曲库，存成可编辑的简谱文本。

来源：https://jiko-official.top/delta/app.js（该站的曲库对象字面量）。
用途：本机当作现成曲目直接演奏 / 当作解析器的真实测试语料（含 :精确拍数、连音、反复线等语法）。
"""

# --- 让本脚本无论放在哪一层子目录，都能 import 到项目根下的模块（play.py / score.py / keymap.py …）---
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d and not _os.path.isfile(_os.path.join(_d, "play.py")):
    _p = _os.path.dirname(_d)
    if _p == _d:
        break
    _d = _p
if _d and _d not in _sys.path:
    _sys.path.insert(0, _d)
import json, os, re, sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'refs', 'jiko_app.js')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'songs')
os.makedirs(OUT, exist_ok=True)

src = open(SRC, encoding='utf-8', errors='replace').read()

# 每个曲目对象形如 { title: "xxx", ..., bpm: 122, score: `...` } 或 jianpu: `...`
pat = re.compile(
    r'\{\s*title:\s*"(?P<title>[^"]*)"(?P<meta>.*?)'
    r'(?:score|jianpu):\s*`(?P<body>.*?)`\s*\}',
    re.S)


def unescape_js(s: str) -> str:
    """把 JS 模板字面量里的转义还原成真字符。"""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            n = s[i + 1]
            out.append({'n': '\n', 't': '\t', 'r': '\r', '`': '`',
                        '\\': '\\', "'": "'", '"': '"', '$': '$'}.get(n, '\\' + n))
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def field(meta: str, name: str):
    m = re.search(rf'{name}:\s*"([^"]*)"', meta)
    return m.group(1) if m else None


rows, seen = [], set()
for m in pat.finditer(src):
    title = m.group('title').strip()
    body = unescape_js(m.group('body')).strip()
    if not body or title in seen:
        continue
    seen.add(title)
    bpm = None
    mb = re.search(r'bpm:\s*([\d.]+)', m.group('meta'))
    if mb:
        bpm = float(mb.group(1))
    detail = field(m.group('meta'), 'detail') or ''
    key = field(m.group('meta'), 'key') or ''
    meter = field(m.group('meta'), 'meter') if 'meter:' in m.group('meta') else ''
    # detail 里经常写着 "1=C · 4/4 · 122 BPM · ..."
    if not key:
        mk = re.search(r'1=([A-Ga-g#b]+)', detail)
        key = ('1=' + mk.group(1)) if mk else '1=C'
    if not meter:
        mm = re.search(r'(\d)/(\d)', detail)
        meter = f'{mm.group(1)}/{mm.group(2)}' if mm else '4/4'
    if bpm is None:
        mbm = re.search(r'([\d.]+)\s*BPM', detail)
        bpm = float(mbm.group(1)) if mbm else 90.0
    rows.append(dict(title=title, bpm=bpm, key=key, meter=meter, detail=detail, body=body))


def safe(name):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', name).strip(' .')
    return s or '未命名'


manifest = []
for r in rows:
    name = safe(r['title'])
    path = os.path.join(OUT, name + '.jianpu')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f"TITLE={r['title']}\n")
        f.write(f"BPM={r['bpm']:g}\n")
        f.write(f"KEY={r['key']}\n")
        f.write(f"METER={r['meter']}\n")
        if r['detail']:
            f.write(f"// 来源: https://jiko-official.top/delta 曲库 · {r['detail']}\n")
        f.write('\n')
        f.write(r['body'].rstrip() + '\n')
    manifest.append(dict(title=r['title'], bpm=r['bpm'], key=r['key'],
                         meter=r['meter'], file=path, chars=len(r['body'])))

json.dump(manifest, open(os.path.join(OUT, '_manifest.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print(f"抽出 {len(rows)} 首曲目 → {OUT}")
for r in manifest:
    print(f"  {r['title']:12s} {r['bpm']:>5g} BPM  {r['key']:5s} {r['meter']:4s} {r['chars']:>6d} 字符")
