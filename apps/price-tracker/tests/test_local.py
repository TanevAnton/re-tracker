"""Offline regression tests: no marketplace traffic, no paid vision calls."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from io import BytesIO
from tracker.collection import collect_page, browser_allowed
from tracker.http import Client, SourceError
from tracker.parsers import page_problem
from tracker.visual import parse_card
from tracker.importing import read_import
from tracker.local import merge_database, validate_database
from tracker.runtime import lock, point_output
from tracker.storage import connect, save, export
from tracker.matching import match
from test_tracker import GPU, CPU, CATALOG, row, FIXTURES

CFG=dict(automation='allowed',browser=True,visual=True,browser_access_verified=False)


class FallbackTests(unittest.TestCase):
    def test_http_success_never_launches_browser(self):
        client=Mock();client.get.return_value=(FIXTURES/'desktop.html').read_text();browser=Mock()
        rows,nxt,attempts=collect_page('desktop','https://desktop.bg/search',CFG,client,browser)
        self.assertTrue(rows);self.assertEqual(rows[0]['extraction_method'],'http');browser.get.assert_not_called()

    def test_rendering_and_parser_failures_launch_real_adapter(self):
        for body in ('<html>Please enable Javascript</html>','<html>Markup changed</html>'):
            client=Mock();client.get.return_value=body;browser=Mock()
            browser.get.return_value=([{'title':'rendered'}],None,[dict(method='browser_dom',outcome='ok')])
            rows,_,attempts=collect_page('desktop','https://desktop.bg/search',CFG,client,browser)
            self.assertEqual(rows[0]['title'],'rendered');self.assertEqual(len(attempts),2)
            browser.get.assert_called_once()

    def test_blocked_sources_never_launch_browser(self):
        for code in ('robots_disallowed','robots_http_403','security_challenge','login_required','access_denied','http_429','http_403','http_503'):
            client=Mock();client.get.side_effect=SourceError(code);browser=Mock()
            with self.assertRaises(SourceError) as ctx:collect_page('desktop','https://desktop.bg/',CFG,client,browser)
            browser.get.assert_not_called();self.assertEqual(ctx.exception.attempts[0]['outcome'],code)

    def test_403_requires_verified_browser_access(self):
        self.assertFalse(browser_allowed(SourceError('http_403'),CFG))
        self.assertTrue(browser_allowed(SourceError('http_403'),dict(CFG,browser_access_verified=True)))
        self.assertFalse(browser_allowed(SourceError('security_challenge'),dict(CFG,browser_access_verified=True)))

    def test_policy_stops_before_http(self):
        for policy in ('permission_required','automation_prohibited','unknown'):
            client=Mock();browser=Mock()
            with self.assertRaises(SourceError):collect_page('pazaruvaj','https://www.pazaruvaj.com/',dict(CFG,automation=policy),client,browser)
            client.get.assert_not_called();browser.get.assert_not_called()

    def test_browser_challenge_is_final(self):
        client=Mock();client.get.return_value='<html>Markup changed</html>'
        browser=Mock();browser.get.side_effect=SourceError('security_challenge')
        with self.assertRaises(SourceError) as ctx:collect_page('desktop','https://desktop.bg/',CFG,client,browser)
        self.assertEqual([a['outcome'] for a in ctx.exception.attempts],['parser_no_cards','security_challenge'])

    def test_robots_wildcards_and_allow_precedence(self):
        client=Client(['www.pazaruvaj.com'])
        robots='User-agent: *\nDisallow: /*?st=\nDisallow: /p/*\nAllow: /p/allowed$'
        with patch.object(client,'request',return_value=robots):
            with self.assertRaisesRegex(SourceError,'robots_disallowed'):client.check_robots('https://www.pazaruvaj.com/?st=CPU')
            client.check_robots('https://www.pazaruvaj.com/p/allowed')
            with self.assertRaises(SourceError):client.check_robots('https://www.pazaruvaj.com/p/allowed-more')

    def test_error_categories(self):
        self.assertEqual(page_problem('<html><input type="password"></html>'),'login_required')
        self.assertEqual(page_problem('<html>Checking your browser</html>'),'security_challenge')
        client=Client(['desktop.bg'])
        error=HTTPError('https://desktop.bg/',403,'Forbidden',{},BytesIO(b'<html>Verify you are human</html>'))
        with patch.object(client,'check_robots'),patch.object(client,'request',side_effect=error):
            with self.assertRaises(SourceError) as ctx:client.get('https://desktop.bg/')
            self.assertEqual(ctx.exception.category,'challenge');self.assertEqual(ctx.exception.http_status,403)


class VisualAndMatchingTests(unittest.TestCase):
    def test_card_ocr_is_always_review_and_keeps_unknowns(self):
        r=parse_card([dict(text='MSI RTX 3060 12GB',confidence=.99),dict(text='240 €',confidence=.98)],'https://www.olx.bg/d/ad/a','olx')
        self.assertEqual(r['price_eur'],240);self.assertIsNone(r['shipping_eur'])
        self.assertEqual(r['price_kind'],'asking');self.assertEqual(r['delivery_bg'],'unknown')
        self.assertEqual(match(r,GPU),('review','visual_requires_review'))
        self.assertEqual(set(r['evidence']),{'title','price_text'})

    def test_multiple_prices_missing_price_and_unclear_identity(self):
        r=parse_card([dict(text='240 €',confidence=1),dict(text='200 €',confidence=1)],'https://desktop.bg/x','desktop',title='RTX 3060 12GB')
        self.assertIsNone(r['price_eur']);self.assertIsNone(r['price']);self.assertEqual(match(r,GPU)[0],'review')
        r=parse_card([],'https://desktop.bg/x','desktop',title='RTX 3060 12GB')
        self.assertIsNone(r['shipping_eur']);self.assertIsNone(r['price_eur'])
        with self.assertRaises(SourceError):parse_card([dict(text='200 €',confidence=1)],'https://desktop.bg/x','desktop')

    def test_rendered_text_and_currency_conversion(self):
        r=parse_card([dict(text='391.17 лв. / 200 €',confidence=.8)],'https://desktop.bg/x','desktop',title='RTX 3060 12GB',method='browser_text')
        self.assertEqual(r['price_eur'],200);self.assertEqual(r['extraction_method'],'browser_text')

    def test_catalog_ram_and_storage_specs(self):
        ram=next(m for m in CATALOG if m['category']=='ram')
        self.assertEqual(match(row('Kingston Fury Beast 32GB DDR5 6000 CL30 2x16GB'),ram)[0],'accepted')
        self.assertEqual(match(row('Kingston Fury Beast 32GB DDR5 6000 CL30'),ram),('review','ram_kit_unspecified'))
        self.assertEqual(match(row('Kingston Fury Beast 32GB DDR5 6000 CL30 1x32GB'),ram)[0],'rejected')
        ssd=next(m for m in CATALOG if m['id']=='samsung-990-pro-1tb')
        self.assertEqual(match(row('Samsung 990 PRO 1TB'),ssd)[0],'accepted')
        self.assertEqual(match(row('Samsung 990 PRO 2TB'),ssd)[0],'rejected')
        self.assertEqual(match(row('Samsung 990 PRO 1TB heatsink'),ssd)[0],'review')


class LocalPersistenceTests(unittest.TestCase):
    def observation(self,price=200,run_id='one',**extra):
        r=row(model_id=GPU['id'],source='olx',url='https://www.olx.bg/d/ad/a',observed_at=datetime.now(timezone.utc).isoformat(),run_id=run_id,status='accepted',market='classifieds',mode='live',**extra)
        r['price_eur']=price
        return r

    def test_restore_merge_preserves_conflicts_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.sqlite';b=Path(tmp)/'b.sqlite'
            first=self.observation();second=dict(first,price_eur=210,run_id='two')
            db=connect(a);save(db,[first]);db.close()
            db=connect(b);save(db,[second]);db.close()
            merge_database(a,b);merge_database(a,b)
            db=connect(b)
            self.assertEqual(json.loads(db.execute('SELECT payload FROM observations').fetchone()[0])['price_eur'],210)
            self.assertEqual(db.execute('SELECT count(*) FROM observation_events').fetchone()[0],2);db.close()
            validate_database(b)

    def test_same_day_reruns_archive_without_inflating_daily_rows(self):
        db=connect(':memory:');r=self.observation();save(db,[r,r]);save(db,[dict(r,price_eur=220,run_id='two')])
        self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM observation_events').fetchone()[0],2);db.close()

    def test_older_import_cannot_replace_a_newer_same_day_price(self):
        db=connect(':memory:')
        latest=self.observation();latest['observed_at']='2026-09-07T15:00:00+00:00'
        older=dict(latest,price_eur=100,observed_at='2026-09-07T10:00:00+00:00',run_id='import')
        save(db,[latest]);save(db,[older])
        self.assertEqual(json.loads(db.execute('SELECT payload FROM observations').fetchone()[0])['price_eur'],200)
        self.assertEqual(db.execute('SELECT count(*) FROM observation_events').fetchone()[0],2)
        db.close()

    def test_retail_and_classified_new_stay_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=connect(':memory:');r=self.observation();r['condition']='new'
            r2=dict(r,source='desktop',url='https://desktop.bg/a',market='retail',price_kind='offer',price_eur=300)
            save(db,[r,r2]);run=dict(run_id='one',finished_at=r['observed_at'],mode='live',jobs=[dict(source=s,model_id=GPU['id'],status='ok') for s in ('olx','desktop')])
            s=export(db,[GPU],tmp,run)
            self.assertEqual(sorted(x['median_eur'] for x in s if x['sample_count']),[200,300]);db.close()

    def test_lock_and_atomic_report_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'a.sqlite'
            with lock(db):
                with self.assertRaisesRegex(RuntimeError,'lock'):
                    with lock(db):pass
            with lock(db):pass
            old=Path(tmp)/'old';new=Path(tmp)/'new';old.mkdir();new.mkdir()
            point_output(Path(tmp)/'output',old);point_output(Path(tmp)/'output',new)
            self.assertEqual((Path(tmp)/'output').resolve(),new.resolve())

    def test_import_validation_and_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'import.json'
            r=dict(source='olx',model_id=GPU['id'],title='RTX 3060 12GB',url='https://www.olx.bg/d/ad/a',observed_at=datetime.now(timezone.utc).isoformat(),price=None,condition='used',availability='listed',delivery_bg='confirmed',confidence=1)
            data=dict(mode='live',method='assisted_visual',authorization='user-provided observation',observations=[r]);path.write_text(json.dumps(data))
            sources={'olx':dict(hosts=['www.olx.bg'],market='classifieds')}
            rows,_=read_import(path,[GPU],sources,'one',approved=True)
            self.assertIsNone(rows[0]['price_eur']);self.assertEqual(rows[0]['status'],'review');self.assertEqual(rows[0]['delivery_bg'],'unknown')
            r['price']=200;r['currency']='EUR';r['delivery_evidence']='OLX delivery badge'
            path.write_text(json.dumps(data));rows,_=read_import(path,[GPU],sources,'one')
            self.assertEqual(rows[0]['status'],'review')
            rows,_=read_import(path,[GPU],sources,'one',approved=True);self.assertEqual(rows[0]['status'],'accepted')
            data['mode']='fixture';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'fixture'):read_import(path,[GPU],sources,'one')
