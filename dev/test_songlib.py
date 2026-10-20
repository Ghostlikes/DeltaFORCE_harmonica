"""离线曲库回归测试；只用合成元数据，不访问网络、不发送按键。"""
import contextlib
import io
import http.client
import json
import os
from email.message import Message
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jiko_lib
import songlib


def row(song_id='one', title='测试曲'):
    return dict(songId=song_id, title=title, authorName='X&amp;Y', bpm=120)


def response(items, total):
    return json.dumps(dict(code=0, data=dict(items=items, total=total))).encode()


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='harmonica_library_test_', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.patch = mock.patch.object(songlib, 'CACHE_DIR', self.tmp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_denial_notice_is_not_a_score(self):
        text = '// ACCESS DENIED\nglobalThis.COMMUNITY_SONGS = ' + json.dumps([
            dict(title='请通过官方站点访问曲库', source='ACCESS DENIED', jianpu='1 2 3')])
        with self.assertRaisesRegex(RuntimeError, '停止|限制|拒绝'):
            jiko_lib.parse_library(text)

    def test_removed_sources_not_advertised(self):
        self.assertNotIn('jiko', songlib.SOURCE_NAMES)
        self.assertNotIn('shushu', songlib.SOURCE_NAMES)

    def test_permanent_http_error_is_not_retried(self):
        error = urllib.error.HTTPError('https://example.org', 403, 'Forbidden', Message(), None)
        self.addCleanup(error.close)
        with mock.patch('urllib.request.urlopen', side_effect=error) as get, mock.patch('time.sleep'):
            with self.assertRaises(RuntimeError):
                songlib.http_get('https://example.org', tries=3)
            self.assertEqual(get.call_count, 1)

    def test_incomplete_read_is_retried_then_wrapped(self):
        error = http.client.IncompleteRead(b'partial', 100)
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.side_effect = error
        with mock.patch('urllib.request.urlopen', return_value=resp) as get, \
             mock.patch('time.sleep') as sleep:
            with self.assertRaises(RuntimeError) as caught:
                songlib.http_get('https://example.org')
            self.assertIs(caught.exception.__cause__, error)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(resp.read.call_count, 2)
            sleep.assert_called_once_with(1)

    def test_incomplete_read_falls_back_to_explicit_stale_cache(self):
        item = dict(src='shallow', id='one', title='测试曲', artist='', chart=False,
                    url='https://example.org/song')
        songlib._cache_write('shallow_v2.json', [item])
        path = Path(self.tmp.name)/'shallow_v2.json'
        now = songlib.time.time()
        os.utime(path, (now - 86400, now - 86400))
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.side_effect = http.client.IncompleteRead(b'partial', 100)
        out = io.StringIO()
        with mock.patch.object(songlib, '_shallow_token', return_value='test'), \
             mock.patch('urllib.request.urlopen', return_value=resp) as get, \
             mock.patch('time.sleep'), contextlib.redirect_stdout(out):
            self.assertEqual(songlib.shallow_catalog(force=True, verbose=True), [item])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(resp.read.call_count, 2)
        self.assertIn('旧缓存', out.getvalue())
        self.assertNotIn('（在线）', out.getvalue())

    def test_shallow_pagination_and_html_entities(self):
        with mock.patch.object(songlib, '_shallow_token', return_value='test'), \
             mock.patch.object(songlib, 'http_get', side_effect=[response([row()], 2), response([row('two')], 2)]):
            songs = songlib.shallow_catalog(force=True)
        self.assertEqual(len(songs), 2)
        self.assertEqual(songs[0]['artist'], 'X&Y')
        self.assertFalse(songs[0]['chart'])

    def test_business_error_is_not_empty_success(self):
        with mock.patch.object(songlib, '_shallow_token', return_value='test'), \
             mock.patch.object(songlib, 'http_get', return_value=b'{"code":500,"message":"unavailable"}'):
            with self.assertRaises(RuntimeError):
                songlib.shallow_catalog(force=True)

    def test_repeated_page_is_rejected(self):
        with mock.patch.object(songlib, '_shallow_token', return_value='test'), \
             mock.patch.object(songlib, 'http_get', return_value=response([row()], 2)):
            with self.assertRaisesRegex(RuntimeError, '重复|分页|完整'):
                songlib.shallow_catalog(force=True)

    def test_truncated_catalog_is_not_cached(self):
        with mock.patch.object(songlib, '_shallow_token', return_value='test'), \
             mock.patch.object(songlib, 'http_get', side_effect=[response([row()], 2), response([], 2)]):
            with self.assertRaises(RuntimeError):
                songlib.shallow_catalog(force=True)
        self.assertFalse((Path(self.tmp.name)/'shallow_v2.json').exists())

    def test_invalid_source_has_clear_error(self):
        with self.assertRaisesRegex(ValueError, '来源'):
            songlib.catalog('invalid')

    def test_all_sources_failed_is_not_no_matches(self):
        with mock.patch.object(songlib, 'catalog', side_effect=RuntimeError('network unavailable')):
            with self.assertRaisesRegex(RuntimeError, '失败|不可用'):
                songlib.search('测试曲', sources=['shallow', 'visualizer'])

    def test_partial_failure_keeps_other_results(self):
        good = dict(src='shallow', id='one', title='测试曲', artist='', chart=False)
        def get(source, **kwargs):
            if source == 'shallow':
                return [good]
            raise RuntimeError('network unavailable')
        with mock.patch.object(songlib, 'catalog', side_effect=get):
            self.assertEqual(songlib.search('测试曲', sources=['shallow', 'visualizer']), [good])

    def test_empty_query_does_not_access_network(self):
        with mock.patch.object(songlib, 'catalogs') as get:
            self.assertEqual(songlib.search('  '), [])
            get.assert_not_called()

    def test_cli_prints_link_only_results(self):
        item = dict(src='shallow', id='one', title='测试曲', artist='', bpm=120,
                    chart=False, url='https://example.org/song/one')
        out = io.StringIO()
        with mock.patch.object(songlib, 'search', return_value=[item]), contextlib.redirect_stdout(out):
            self.assertEqual(songlib._cli(['--search', '测试曲']), 0)
        self.assertIn(item['url'], out.getvalue())


    def test_stale_cache_fallback_is_explicit(self):
        item = dict(src='shallow', id='one', title='测试曲', artist='', chart=False,
                    url='https://example.org/song')
        songlib._cache_write('shallow_v2.json', [item])
        path = Path(self.tmp.name)/'shallow_v2.json'
        import time
        os.utime(path, (time.time()-30000, time.time()-30000))
        out = io.StringIO()
        with mock.patch.object(songlib, '_shallow_token', side_effect=RuntimeError('offline')), contextlib.redirect_stdout(out):
            self.assertEqual(songlib.shallow_catalog(force=True, verbose=True), [item])
        self.assertIn('旧缓存', out.getvalue())

    def test_corrupt_cache_is_refetched(self):
        (Path(self.tmp.name)/'shallow_v2.json').write_text('{broken', encoding='utf-8')
        with mock.patch.object(songlib, '_shallow_token', return_value='test'), \
             mock.patch.object(songlib, 'http_get', return_value=response([row()], 1)) as get:
            self.assertEqual(len(songlib.shallow_catalog()), 1)
            self.assertEqual(get.call_count, 1)

    def test_business_401_refreshes_once(self):
        with mock.patch.object(songlib, '_shallow_token', side_effect=['old', 'new']) as tok, \
             mock.patch.object(songlib, 'http_get', side_effect=[b'{"code":401}', response([row()], 1)]) as get:
            self.assertEqual(len(songlib.shallow_catalog(force=True)), 1)
        self.assertEqual(tok.call_count, 2)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs['headers']['X-Anonymous-Token'], 'new')

    def test_second_401_is_not_an_infinite_refresh(self):
        with mock.patch.object(songlib, '_shallow_token', return_value='test') as tok, \
             mock.patch.object(songlib, 'http_get', return_value=b'{"code":401}') as get:
            with self.assertRaises(RuntimeError):
                songlib.shallow_catalog(force=True)
        self.assertEqual(tok.call_count, 2)
        self.assertEqual(get.call_count, 2)

    def test_missing_total_is_rejected(self):
        with mock.patch.object(songlib, '_shallow_token', return_value='test'), \
             mock.patch.object(songlib, 'http_get', return_value=b'{"code":0,"data":{"items":[]}}'):
            with self.assertRaises(RuntimeError):
                songlib.shallow_catalog(force=True)

    def test_git_tree_truncation_is_rejected(self):
        with mock.patch.object(songlib, 'http_get', return_value=b'{"tree":[],"truncated":true}'):
            with self.assertRaises(RuntimeError):
                songlib.visualizer_catalog(force=True)

    def test_visualizer_download_and_roundtrip(self):
        import base64
        import hashlib
        import score
        raw = b'TITLE=Example\nBPM=120\nKEY=1=C\nMETER=4/4\n1 2_ 3_ 5- | 0 1:1.5 2:0.5 3 |\n'
        sha = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        payload = json.dumps(dict(encoding='base64', content=base64.b64encode(raw).decode())).encode()
        item = dict(src='visualizer', id='songs/example.txt', title='测试曲', chart=True,
                    sha=sha, url='https://github.com/example')
        with mock.patch.object(songlib, 'http_get', return_value=payload):
            path, message = songlib.download(item, self.tmp.name, verbose=False)
        self.assertIsNotNone(path, message)
        parsed = score.parse_any(path)
        original = score.parse_any('example.txt', text=raw.decode())
        self.assertEqual([(n.pitch,n.start,n.dur) for n in parsed.notes],
                         [(n.pitch,n.start,n.dur) for n in original.notes])
        self.assertIn(item['url'], Path(path).read_text(encoding='utf-8'))

    def test_git_content_mismatch_never_saves(self):
        item = dict(src='visualizer', id='songs/x.txt', title='测试曲', chart=True,
                    sha='0'*40, url='https://github.com/example')
        with mock.patch.object(songlib, 'http_get', return_value=b'{"encoding":"base64","content":"MSAyIDM="}'):
            path, message = songlib.download(item, self.tmp.name, verbose=False)
        self.assertIsNone(path)
        self.assertIn('校验失败', message)
        self.assertFalse(list(Path(self.tmp.name).glob('*.jianpu')))

    def test_link_source_never_downloads(self):
        with mock.patch.object(songlib, 'http_get') as get:
            path, _ = songlib.download(dict(src='je', chart=False, url='https://example.org'))
        self.assertIsNone(path)
        get.assert_not_called()

    def test_same_notes_different_bpm_not_reused(self):
        song = dict(title='测试曲', bpm=90, key='1=C', meter='4/4', jianpu='1 2 3 4')
        first, _ = jiko_lib.download(song, self.tmp.name, verbose=False)
        second, _ = jiko_lib.download(dict(song, bpm=120), self.tmp.name, verbose=False)
        self.assertNotEqual(first, second)
        self.assertIn('BPM=90', Path(first).read_text(encoding='utf-8'))
        third, _ = jiko_lib.download(dict(song, bpm=120), self.tmp.name, verbose=False)
        self.assertEqual(second, third)

    def test_reserved_windows_names_are_safe(self):
        self.assertEqual(jiko_lib.safe_name('CON'), '_CON')
        self.assertNotIn('/', jiko_lib.safe_name('../../escape'))

    def test_removed_source_never_contacts_network(self):
        with mock.patch.object(songlib, 'http_get') as get:
            with self.assertRaises(ValueError):
                songlib.search('测试曲', sources=['jiko'])
        get.assert_not_called()

    def test_noninteractive_search_never_prompts(self):
        import play
        from types import SimpleNamespace
        args = SimpleNamespace(source='visualizer', refresh_lib=False, force=False)
        item = dict(src='visualizer', id='one', title='测试曲', artist='', chart=True, url='https://example.org')
        with mock.patch.object(songlib, 'search', return_value=[item, dict(item,id='two')]), \
             mock.patch.object(songlib, 'download', return_value=('example.jianpu','ok')), \
             mock.patch('builtins.input', side_effect=AssertionError('must not prompt')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(play.download_by_name(args, '测试曲'), 'example.jianpu')


if __name__ == '__main__':
    unittest.main(verbosity=2)
