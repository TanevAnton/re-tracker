"""Persistence and CLI contracts, using fixture data only."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tracker.local import publish, schedule
from tracker.parsers import parse, money
from tracker.storage import connect
from test_tracker import FIXTURES

APP=Path(__file__).resolve().parents[1]


class OperationTests(unittest.TestCase):
    def test_ardes_visible_supplier_caveat_overrides_schema_stock(self):
        rows,_=parse('ardes',(FIXTURES/'ardes.html').read_text(),'https://ardes.bg/product/fixture')
        self.assertEqual(rows[0]['price_eur'],222.99)
        self.assertEqual(rows[0]['availability'],'supplier_confirmation')
        self.assertEqual(rows[0]['condition'],'unknown')
        self.assertIsNone(rows[0]['shipping_eur'])

    def test_ambiguous_or_negative_money_never_becomes_price(self):
        for text in ('200 € 250 €','100 EUR / 200 EUR','-200 €'):
            with self.assertRaises(ValueError):money(text)
        self.assertEqual(money('391.17 лв. / 200 €')[2],200)

    def test_fixture_cli_persistence_manifest_and_production_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'fixture.sqlite';out=Path(tmp)/'output'
            cmd=[sys.executable,'-m','tracker','--fixtures',str(FIXTURES),'--source','olx','--model','rtx-3060-12gb','--database',str(db),'--output',str(out)]
            result=subprocess.run(cmd,cwd=APP,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run=json.loads((out/'status.json').read_text());self.assertEqual(run['mode'],'fixture')
            self.assertEqual(run['collected_rows'],2)
            self.assertEqual(json.loads((out/'manifest.json').read_text())['run_id'],run['run_id'])
            # Remove the fixture selector: the same DB must fail BEFORE any network.
            cmd=cmd[:3]+cmd[5:]
            result=subprocess.run(cmd,cwd=APP,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('separate databases',result.stdout)

    def test_invalid_restore_does_not_touch_existing_database(self):
        from tracker.local import merge_database
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'live.sqlite';bad=Path(tmp)/'bad.sqlite'
            db=connect(target);db.execute("INSERT INTO runs VALUES('original','{}')");db.commit();db.close()
            before=target.read_bytes();bad.write_text('not sqlite')
            with self.assertRaises(Exception):merge_database(bad,target)
            self.assertEqual(target.read_bytes(),before)

    def test_fixture_publication_is_rejected_before_git_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'output';output.mkdir();(output/'status.json').write_text(json.dumps(dict(mode='fixture')))
            with patch('tracker.local.DATA',Path(tmp)),patch('tracker.local.verify_repository'),patch('tracker.local.git') as git:
                with self.assertRaisesRegex(ValueError,'Fixture'):publish('any-id')
                git.assert_not_called()
