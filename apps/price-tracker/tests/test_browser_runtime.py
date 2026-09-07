"""Opt-in real Chrome + Apple Vision tests using synthetic local content only."""
import os
from pathlib import Path
import unittest
from tracker.browser import Browser
from tracker.http import Client
from tracker.matching import match
from test_tracker import GPU, FIXTURES


@unittest.skipUnless(os.getenv('TRACKER_BROWSER_TESTS')=='1','opt in with TRACKER_BROWSER_TESTS=1')
class BrowserRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.browser=Browser(Client(['desktop.bg']),dict(card_selector='article',visual=True))
        self.browser.start()
        self.page=self.browser.context.new_page()
        self.addCleanup(self.browser.close)

    def test_real_rendered_dom(self):
        self.page.set_content((FIXTURES/'desktop.html').read_text())
        rows,_,steps=self.browser.extract(self.page,'desktop','https://desktop.bg/search')
        self.assertGreater(len(rows),1)
        self.assertTrue(all(r['extraction_method']=='browser_dom' for r in rows))

    @unittest.skipUnless(Path('.local/bin/vision-ocr').is_file(),'Apple Vision helper not built')
    def test_real_screenshot_ocr_fallback(self):
        self.page.set_content('''<article style="width:420px;height:140px;background:white">
        <a href="https://desktop.bg/fixture-only" aria-label="MSI RTX 3060 12GB"><canvas width="420" height="140"></canvas></a></article>
        <script>const c=document.querySelector('canvas').getContext('2d');
        c.fillStyle='white';c.fillRect(0,0,420,140);c.fillStyle='black';c.font='32px Arial';
        c.fillText('MSI RTX 3060 12GB',12,42);c.fillText('240 EUR',12,100);</script>''')
        rows,_,steps=self.browser.extract(self.page,'desktop','https://desktop.bg/fixture-only')
        self.assertEqual(len(rows),1)
        r=rows[0];self.assertEqual(r['price_eur'],240)
        self.assertEqual(r['extraction_method'],'visual_ocr')
        self.assertEqual(match(r,GPU)[0],'review');self.assertIsNone(r['shipping_eur'])
        self.assertEqual(steps[0]['outcome'],'parser_no_cards')
