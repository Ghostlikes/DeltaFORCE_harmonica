"""CLI 返回码回归；配置/导出只写临时目录，不联网、不发按键。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlayExitTests(unittest.TestCase):
    def invoke(self, arguments, directory):
        wrapper = ('import harmonica_config,runpy,sys; '
                   'harmonica_config.CONFIG_PATH=sys.argv[1]; '
                   'sys.argv=["play.py"]+sys.argv[2:]; '
                   'runpy.run_path("play.py",run_name="__main__")')
        return subprocess.run([sys.executable, '-c', wrapper, str(Path(directory)/'config.json')]
                              + arguments, cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=20,
                              env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'))

    def test_export_path_result_is_success_not_exit_error(self):
        with tempfile.TemporaryDirectory(prefix='harmonica_cli_', dir=os.environ.get('TMPDIR')) as directory:
            target = Path(directory)/'export.jianpu'
            result = self.invoke(['--song', 'songs/暗号.jianpu', '--export', 'jianpu',
                                  '--export-path', str(target), '--timing', 'standard'], directory)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(target.exists())

    def test_removed_source_failure_has_nonzero_exit_code(self):
        with tempfile.TemporaryDirectory(prefix='harmonica_cli_', dir=os.environ.get('TMPDIR')) as directory:
            result = self.invoke(['--song-search', '测试曲', '--source', 'jiko',
                                  '--timing', 'standard'], directory)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertIn('已移除', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
