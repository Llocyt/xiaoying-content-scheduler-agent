"""Exercise the public entry point across processes and persistent storage."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.input = self.folder / 'input.json'
        self.input.write_text(json.dumps({'request_id': 'cli-test', 'asset_id': 'M01',
            'requested_slot': '2026-11-01T19:00+08:00'}), encoding='utf-8')

    def call(self, *args):
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable, '-m', 'scheduler', '--input', str(self.input),
            '--db', str(self.folder / 'draft.sqlite'), *args], cwd=ROOT, env=env,
            capture_output=True, text=True, encoding='utf-8', timeout=15)

    def test_process_replay_reuses_draft(self):
        first, second = self.call(), self.call()
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(json.loads(second.stdout)['result']['save']['save_status'], 'existing')

    def test_output_failure_retains_business_result(self):
        result = self.call('--output', str(self.folder))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['result']['save']['save_status'], 'saved')
        self.assertEqual(json.loads(result.stderr)['status'], 'artifact_error')

    def test_output_must_not_overwrite_input(self):
        original = self.input.read_bytes()
        result = self.call('--output', str(self.input))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.input.read_bytes(), original)

    def test_save_failure_exit_status(self):
        result = self.call('--fail-save')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['result']['status'], 'save_failed')
