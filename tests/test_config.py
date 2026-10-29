import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scheduler.config import load_env_file
from scheduler.model import ModelError, OpenAICompatibleModel


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'model.env'

    def test_local_configuration_loads_without_executing(self):
        self.path.write_text('# config\nMODEL_API_KEY="fake=key"\nMODEL_NAME=test\nMODEL_BASE_URL=http://example.test:8000\nMODEL_ALLOW_HTTP=1\n', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True):
            load_env_file(self.path)
            model = OpenAICompatibleModel()
            self.assertEqual(model.key, 'fake=key')
            self.assertEqual(model.base, 'http://example.test:8000/v1')

    def test_environment_takes_precedence(self):
        self.path.write_text('MODEL_NAME=file-model\n', encoding='utf-8')
        with patch.dict(os.environ, {'MODEL_NAME': 'process-model'}, clear=True):
            load_env_file(self.path)
            self.assertEqual(os.environ['MODEL_NAME'], 'process-model')

    def test_invalid_file_does_not_leak_secret_or_partially_apply(self):
        self.path.write_text('MODEL_NAME=first\nSECRET=private-value\n', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as error:
                load_env_file(self.path)
            self.assertNotIn('private-value', str(error.exception))
            self.assertNotIn('MODEL_NAME', os.environ)

    def test_remote_http_requires_opt_in(self):
        with patch.dict(os.environ, {'MODEL_API_KEY': 'fake', 'MODEL_NAME': 'test',
                                     'MODEL_BASE_URL': 'http://example.test:8000/v1'}, clear=True):
            with self.assertRaises(ModelError):
                OpenAICompatibleModel()

    def test_exact_loopback_does_not_allow_similar_remote_hostname(self):
        with patch.dict(os.environ, {'MODEL_API_KEY': 'fake', 'MODEL_NAME': 'test',
                                     'MODEL_BASE_URL': 'http://localhost.evil.test:8000/v1'}, clear=True):
            with self.assertRaises(ModelError):
                OpenAICompatibleModel()

    def test_invalid_urls_rejected_even_when_http_allowed(self):
        for base in ('ftp://example.test', 'http://user:password@example.test/v1',
                     'http://example.test:bad', 'https://example.test/v1?key=secret'):
            with self.subTest(base=base), patch.dict(os.environ, {'MODEL_API_KEY': 'fake', 'MODEL_NAME': 'test',
                    'MODEL_BASE_URL': base, 'MODEL_ALLOW_HTTP': '1'}, clear=True):
                with self.assertRaises(ModelError):
                    OpenAICompatibleModel()

    def test_explicit_api_path_preserved(self):
        with patch.dict(os.environ, {'MODEL_API_KEY': 'fake', 'MODEL_NAME': 'test',
                'MODEL_BASE_URL': 'https://example.test/api/v1/'}, clear=True):
            self.assertEqual(OpenAICompatibleModel().base, 'https://example.test/api/v1')

    def test_missing_explicit_file_is_error(self):
        with self.assertRaises(ValueError):
            load_env_file(self.path)
