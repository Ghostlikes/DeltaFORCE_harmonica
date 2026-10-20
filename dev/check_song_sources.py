#!/usr/bin/env python3
"""可重复的实际联网验收（不发按键、不往 songs/ 添加谱面）。

python dev/check_song_sources.py [--refresh] [--downloads]
--downloads 会按需下载 visualizer 当前目录的兼容文本谱到临时目录，验收后清理。
只将来源/数量/解析音符数写入 _cache/source_check.json，不保存曲谱正文或令牌。
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import score
import songlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--downloads', action='store_true')
    args = parser.parse_args()
    report = {'at': datetime.now().astimezone().isoformat(), 'passed': True,
              'sources': {}, 'download_checks': [], 'failures': []}
    for source in ('shallow', 'visualizer'):
        try:
            items = songlib.catalog(source, force=args.refresh, verbose=True)
            ids = {item['id'] for item in items}
            assert len(ids) == len(items) and items, 'empty or duplicate catalog'
            report['sources'][source] = {'count': len(items), 'unique_ids': len(ids)}
        except Exception as exc:
            report['failures'].append(f'{source}: {exc}')
    try:
        hits = songlib.search('春日影', sources=['je'], force=args.refresh, verbose=True)
        assert hits and all(not h['chart'] for h in hits), 'JE search or access classification failed'
        report['sources']['je'] = {'query': '春日影', 'returned': len(hits),
                                   'urls': [h['url'] for h in hits]}
    except Exception as exc:
        report['failures'].append(f'je: {exc}')
    if args.downloads and 'visualizer' in report['sources']:
        with tempfile.TemporaryDirectory(prefix='harmonica_source_check_',
                                         dir=os.environ.get('TMPDIR')) as directory:
            items = songlib.catalog('visualizer')
            for item in items:
                try:
                    path, message = songlib.download(item, directory, verbose=False)
                    assert path, message
                    parsed = score.parse_any(path)
                    assert parsed.notes and any(n.pitch is not None for n in parsed.notes)
                    table, stats = score.to_score_table(parsed)
                    assert table and stats['playable'] > 0
                    report['download_checks'].append({'id': item['id'], 'sha': item['sha'],
                                                      'notes': len(parsed.notes),
                                                      'playable': stats['playable']})
                except Exception as exc:
                    report['failures'].append(f'{item["id"]}: {exc}')
            assert len(report['download_checks']) + len([f for f in report['failures']
                         if f.startswith('songs/')]) == len(items)
    report['passed'] = not report['failures']
    target = ROOT/'_cache'/'source_check.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
