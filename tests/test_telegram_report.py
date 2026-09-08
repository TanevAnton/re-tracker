import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('sender', Path(__file__).parents[1] / 'scripts/telegram_report.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TelegramTests(unittest.TestCase):
    @patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '-123', 'TELEGRAM_THREAD_ID': ''})
    def test_full_unicode_report(self):
        api = Mock()
        api.call.side_effect = [{'id': -123, 'type': 'supergroup'}, {'message_id': 1}]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'report.md'
            data = ('Цени € | 700 → 1000\n' * 1000).encode()
            path.write_bytes(data)
            m.send_report(api, path)
        self.assertEqual(api.call.call_args.kwargs['document'], data)
        self.assertEqual(api.call.call_args.args[0], 'sendDocument')

    @patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '-123'})
    def test_wrong_destination_blocked(self):
        api = Mock()
        api.call.return_value = {'id': -124, 'type': 'supergroup'}
        with self.assertRaises(m.DeliveryError):
            m.destination(api)

    @patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '123'})
    def test_private_chat_blocked(self):
        with self.assertRaises(m.DeliveryError):
            m.destination(Mock())

    def test_network_errors_do_not_leak_token_or_retry(self):
        api = m.Telegram('123:TEST_ONLY')
        api.opener = Mock()
        api.opener.open.side_effect = OSError('https://api.telegram.org/bot123:TEST_ONLY/sendDocument')
        with self.assertRaises(m.DeliveryError) as caught:
            api.call('sendDocument', {}, b'report')
        self.assertNotIn('TEST_ONLY', str(caught.exception))
        self.assertEqual(api.opener.open.call_count, 1)

    def test_empty_file_never_sent(self):
        api = Mock()
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises(m.DeliveryError):
                m.send_report(api, f.name)
        api.call.assert_not_called()

if __name__ == '__main__':
    unittest.main()
