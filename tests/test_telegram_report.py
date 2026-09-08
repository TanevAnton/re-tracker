import importlib.util
import contextlib
import io
import json
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

    @patch.dict(os.environ, {'TELEGRAM_CHAT_ID': " TELEGRAM_CHAT_ID='-123' \n", 'TELEGRAM_THREAD_ID': '  '})
    def test_copied_assignment_and_whitespace(self):
        api = Mock()
        api.call.return_value = {'id': -123, 'type': 'supergroup'}
        self.assertEqual(m.destination(api), {'chat_id': '-123'})

    def test_http_error_classification_never_echoes_response(self):
        api = m.Telegram('123:TEST_ONLY')
        api.opener = Mock()
        for status, description, expected in (
            (401, 'Unauthorized TEST_ONLY', 'bot token'),
            (400, 'Bad Request: chat not found TEST_ONLY', 'cannot find the group'),
            (403, 'Forbidden TEST_ONLY', 'denied access'),
            (400, 'Bad Request: message thread not found TEST_ONLY', 'topic'),
        ):
            with self.subTest(status=status, description=description):
                body = io.BytesIO(json.dumps({'description': description}).encode())
                api.opener.open.side_effect = m.urllib.error.HTTPError('credential-url', status, description, {}, body)
                with self.assertRaises(m.DeliveryError) as caught:
                    api.call('getChat', {})
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn('TEST_ONLY', str(caught.exception))

    @patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '123:TEST_ONLY', 'TELEGRAM_CHAT_ID': '-123', 'TELEGRAM_THREAD_ID': ''})
    @patch('sys.argv', ['telegram_report.py', 'send-secret'])
    def test_secret_report_cli_preserves_text_and_does_not_log_it(self):
        report = '# Private report\nЦени: €1000\n$(touch /tmp/not-executed)\n'
        with patch.dict(os.environ, {'TELEGRAM_REPORT_TEXT': report}):
            with patch.object(m, 'Telegram') as api_type:
                api = api_type.return_value
                api.call.side_effect = [{'id': -123, 'type': 'supergroup'}, {'message_id': 321}]
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    self.assertEqual(m.main(), 0)
                self.assertEqual(api.call.call_args.kwargs['document'], report.encode())
                self.assertNotIn('TELEGRAM_REPORT_TEXT', os.environ)
                self.assertEqual(output.getvalue(), 'Report delivery confirmed.\n')

    @patch.dict(os.environ, {'TELEGRAM_REPORT_TEXT': ''})
    def test_missing_report_never_contacts_telegram(self):
        api = Mock()
        with self.assertRaisesRegex(m.DeliveryError, 'TELEGRAM_REPORT_TEXT'):
            m.send_secret_report(api)
        api.call.assert_not_called()

    @patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '-123', 'TELEGRAM_THREAD_ID': ''})
    def test_configuration_check_only_reads(self):
        api = Mock()
        api.call.side_effect = [{'username': 'retech23_bot'}, {'id': -123, 'type': 'supergroup'}]
        with contextlib.redirect_stdout(io.StringIO()):
            m.check_connection(api)
        self.assertEqual([c.args[0] for c in api.call.call_args_list], ['getMe', 'getChat'])

if __name__ == '__main__':
    unittest.main()
