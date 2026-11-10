import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('synchro_proxy_test', Path(__file__).resolve().parents[2] / 'deploy/youtube_proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class ProxyTests(unittest.TestCase):
    def test_only_youtube_and_exact_ai_hosts_are_allowed(self):
        for host in ['www.youtube.com', 'rr1.googlevideo.com', 'api.openai.com', 'ai-gateway.kilo.ai', 'openrouter.ai']:
            self.assertTrue(proxy.allowed(host), host)
        for host in ['127.0.0.1', '169.254.169.254', 'example.com', 'api.openai.com.evil.example',
                     'evil.api.openai.com', 'openrouter.ai.evil.example', 'youtube.com.evil.example']:
            self.assertFalse(proxy.allowed(host), host)
