import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median


def connect(path):
    if str(path) != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS observations (
      day TEXT NOT NULL, model_id TEXT NOT NULL, source TEXT NOT NULL,
      listing_id TEXT NOT NULL, payload TEXT NOT NULL,
      PRIMARY KEY(day, model_id, source, listing_id));
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS observation_events (
      event_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    ''')
    # Additive migration: preserve legacy daily rows and every future rerun.
    for (payload,) in db.execute('SELECT payload FROM observations').fetchall():
        db.execute('INSERT OR IGNORE INTO observation_events VALUES(?,?)',
                   (hashlib.sha256(payload.encode()).hexdigest(), payload))
    db.commit()
    return db


def save(db, rows):
    for row in rows:
        # One observation per listing/model/day; reruns cannot inflate the sample.
        listing_id = hashlib.sha256((row['url']+'|'+row.get('merchant','')).encode()).hexdigest()[:24]
        row['listing_id'] = listing_id
        payload = json.dumps(row, ensure_ascii=False)
        db.execute('INSERT OR IGNORE INTO observation_events VALUES(?,?)',
                   (hashlib.sha256(payload.encode()).hexdigest(), payload))
        db.execute('''INSERT INTO observations VALUES(?,?,?,?,?)
                   ON CONFLICT(day, model_id, source, listing_id) DO UPDATE SET payload=excluded.payload
                   WHERE julianday(json_extract(excluded.payload, '$.observed_at')) >=
                         julianday(json_extract(observations.payload, '$.observed_at'))''',
                   (row['observed_at'][:10], row['model_id'], row['source'], listing_id, payload))
    db.commit()


def quantile(values, q):
    v = sorted(values)
    if not v:
        return None
    pos = (len(v)-1)*q
    lower = int(pos)
    return round(v[lower] + (v[min(lower+1,len(v)-1)]-v[lower])*(pos-lower),2)


def csv_write(path, rows, fields):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for r in rows:
            # Spreadsheet formula injection protection for untrusted listing text.
            writer.writerow({k: ("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in r.items()})


SUMMARY_FIELDS = ['model_id','name','category','condition','sample_count','merchant_count','min_eur','p25_eur','median_eur','p75_eur','max_eur','delivered_min_eur','shipping_known_count','confidence','observed_at','eligible_for_review','notes']
LISTING_FIELDS = ['model_id','source','title','price_eur','currency','price','shipping_eur','delivery_bg','condition','availability','price_kind','status','reason','observed_at','url','merchant','listing_id', 'market','sku','extraction_method','extraction_confidence','source_url','delivery_evidence','delivery_verified_on','evidence','run_id','mode']


def export(db, catalog, out, run):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.fromisoformat(run['finished_at'])
    cutoff = now - timedelta(hours=36)
    all_rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM observations ORDER BY day')]
    # Latest record of each listing, regardless of date. Keep failed-source data visible as stale.
    latest = {}
    for row in all_rows:
        key = (row['model_id'], row['source'], row['listing_id'])
        if key not in latest or row['observed_at'] > latest[key]['observed_at']:
            latest[key] = row
    current = list(latest.values())
    completed = {(j['source'],j['model_id']) for j in run['jobs'] if j['status']=='ok'}
    for row in current:
        row['fresh'] = cutoff <= datetime.fromisoformat(row['observed_at']) <= now + timedelta(minutes=5)
        row['seen_this_run'] = row.get('run_id') == run['run_id']
        row['source_ok'] = (row['source'],row['model_id']) in completed
    summaries = []
    for model in catalog:
        for condition, market in [('new','retail'),('new','classifieds'),('used','classifieds'),('used','retail'),('new','comparison'),('used','comparison')]:
            candidates = [r for r in current if r['model_id']==model['id'] and r['condition']==condition and r.get('market', 'classifieds' if r.get('price_kind')=='asking' else 'retail')==market and r['status']=='accepted' and r.get('price_eur') is not None and r['fresh'] and r['seen_this_run'] and r['source_ok'] and r.get('mode','live')==run.get('mode','live')]
            # Identical merchant/model/condition should not gain extra weight through cross-listing.
            unique = {}
            for r in candidates:
                merchant = r.get('merchant') or r['url']
                if merchant not in unique or r['price_eur'] < unique[merchant]['price_eur']:
                    unique[merchant] = r
            rows = list(unique.values())
            prices = [r['price_eur'] for r in rows]
            # Broad outlier screen, only with enough independent observations.
            if len(prices) >= 5:
                mid = median(prices)
                rows = [r for r in rows if mid*.4 <= r['price_eur'] <= mid*2.5]
                prices = [r['price_eur'] for r in rows]
            shipping = [r['price_eur']+r['shipping_eur'] for r in rows if r.get('shipping_eur') is not None]
            n = len(prices)
            spread_ok = n >= 3 and quantile(prices,.75) <= quantile(prices,.25)*1.5
            confidence = 'medium' if spread_ok else 'low' if n else 'no_data'
            # Asking prices are not realised sales; no automatic sell/buy recommendation.
            summaries.append(dict(model_id=model['id'],name=model['name'],category=model['category'],condition=condition,market=market,
                sample_count=n,merchant_count=len(unique),min_eur=min(prices) if n else None,p25_eur=quantile(prices,.25),
                median_eur=round(median(prices),2) if n else None,p75_eur=quantile(prices,.75),max_eur=max(prices) if n else None,
                delivered_min_eur=round(min(shipping),2) if shipping else None,shipping_known_count=len(shipping),confidence=confidence,
                observed_at=max((r['observed_at'] for r in rows),default=None),eligible_for_review=bool(spread_ok),
                notes='Classified asking prices; not sold prices' if market=='classifieds' else 'Observed offers; verify checkout and exact SKU'))
    db.execute('INSERT OR REPLACE INTO runs VALUES(?,?)',(run['run_id'],json.dumps(run)))
    db.commit()
    csv_write(out/'summary.csv',summaries,SUMMARY_FIELDS+['market'])
    csv_write(out/'listings.csv',current,LISTING_FIELDS+['fresh','seen_this_run','source_ok'])
    csv_write(out/'review.csv',[r for r in current if r['status']=='review'],LISTING_FIELDS)
    csv_write(out/'history.csv',all_rows,LISTING_FIELDS)
    csv_write(out/'events.csv',[json.loads(r[0]) for r in db.execute('SELECT payload FROM observation_events')],LISTING_FIELDS)
    csv_write(out/'source_status.csv',run['jobs'],['source','model_id','status','detail','pages','rows','truncated','failure_category','attempts','url','alternative'])
    for name, value in [('summary',summaries),('listings',current),('status',run),('catalog',catalog)]:
        (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    return summaries
