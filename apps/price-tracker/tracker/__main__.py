import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit
from uuid import uuid4
import hashlib
from .http import Client, SourceError, category
from .matching import match
from .parsers import parse
from .storage import connect, save, export
from .collection import collect_page
from .browser import Browser
from .runtime import lock, backup, point_output
from .visual import clean
from .importing import read_import


def load_config(path):
    config = json.loads(Path(path).read_text())
    if isinstance(config,list):
        ids = [m['id'] for m in config]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate model IDs')
        for m in config:
            if not m.get('name') or not m.get('query') or not m.get('category'):
                raise ValueError('Model requires id, name, query and category')
    return config


def arguments():
    p = argparse.ArgumentParser(description='Collect Bulgaria PC component price observations')
    p.add_argument('--catalog',default='config/catalog.json')
    p.add_argument('--sources',default='config/sources.json')
    p.add_argument('--database')
    p.add_argument('--output')
    p.add_argument('--model',help='Only this catalog id')
    p.add_argument('--source',help='Only this source')
    p.add_argument('--fixtures',help='Offline parser smoke test; output marked fixture and never uploaded')
    p.add_argument('--max-pages',type=int,default=2)
    p.add_argument('--headed',action='store_true',help='Show the isolated browser when fallback is needed')
    p.add_argument('--browser-channel',default='chrome')
    p.add_argument('--import-file',help='JSON envelope of manual, assisted visual or licensed feed observations')
    p.add_argument('--approved-import',action='store_true',help='Confirm the exact import file has been reviewed')
    args = p.parse_args()
    if args.fixtures and args.import_file: p.error('Fixtures and live imports cannot be combined')
    if args.approved_import and not args.import_file: p.error('--approved-import requires --import-file')
    args.database = args.database or ('.local/fixtures/prices.sqlite' if args.fixtures else '.local/prices.sqlite')
    args.output = args.output or ('.local/fixtures/output' if args.fixtures else '.local/output')
    if not 1 <= args.max_pages <= 10:
        p.error('--max-pages must be 1..10')
    catalog = load_config(args.catalog)
    sources = load_config(args.sources)
    selected = [m for m in catalog if not args.model or m['id']==args.model]
    if not selected:
        p.error('Unknown model')
    if args.source and args.source not in sources:
        p.error('Unknown source')
    return args,catalog,sources,selected


def collect(args,catalog,sources,selected):
    run_id = str(uuid4())
    stamp = datetime.now(timezone.utc).isoformat()
    run = dict(run_id=run_id,started_at=stamp,mode='fixture' if args.fixtures else 'live',execution='import' if args.import_file else 'automatic',jobs=[],schema_version=2)
    restored = Path(args.database).parent/'restored.json'
    if restored.exists(): run['price_data_base'] = json.loads(restored.read_text())['ref']
    db = connect(args.database)
    existing_modes = {json.loads(x[0]).get('mode','live') for x in db.execute('SELECT payload FROM runs')}
    if existing_modes and existing_modes != {run['mode']}:
        db.close()
        raise ValueError('Use separate databases for fixture and live runs')
    all_rows = []
    if args.import_file:
        all_rows,run['jobs'] = read_import(args.import_file,catalog,sources,run_id,args.approved_import)
    for source, cfg in sources.items():
        if args.import_file: break
        if args.source and source != args.source:
            continue
        client = Client(cfg['hosts'])
        browser = Browser(client,cfg,headed=args.headed,channel=args.browser_channel)
        circuit = None
        for model in selected:
            job = dict(source=source,model_id=model['id'],status='ok',detail='',pages=0,rows=0,truncated=False,attempts=[],alternative='approved feed/API or manual import')
            rows = []
            url = cfg['search_url'].format(query=quote_plus(model['query']),slug=quote(model['query'].lower().replace(' ','-')))
            url = model.get('source_urls',{}).get(source,url)
            job['url'] = url
            if not cfg['enabled']:
                job.update(status='disabled',detail=cfg.get('validation','source_disabled'),failure_category='disabled')
            elif cfg.get('product_urls_only') and source not in model.get('source_urls',{}):
                job.update(status='not_configured',detail='exact_product_url_required',failure_category='coverage')
            elif circuit:
                job.update(status='skipped',detail='source_circuit_open: '+circuit,failure_category=category(circuit))
            else:
                try:
                    visited = set()
                    while url and job['pages'] < args.max_pages:
                        if url in visited:
                            raise SourceError('pagination_loop')
                        visited.add(url)
                        if args.fixtures:
                            fixture = Path(args.fixtures)/(source+'.html')
                            if not fixture.exists():
                                raise SourceError('fixture_unavailable')
                            body = fixture.read_text()
                            parsed,next_url = parse(source,body,url)
                            for row in parsed: row.update(extraction_method='fixture',extraction_confidence=0)
                        else:
                            parsed,next_url,attempts = collect_page(source,url,cfg,client,browser)
                            job['attempts'].extend(attempts)
                        for row in parsed:
                            if urlsplit(row['url']).hostname not in cfg['hosts']:
                                continue
                            row['title'] = clean(row['title'])
                            row.update(source=source,model_id=model['id'],category=model['category'],observed_at=datetime.now(timezone.utc).isoformat(),run_id=run_id,market=cfg['market'],mode=run['mode'],source_url=url)
                            row.setdefault('evidence',dict(title=row['title'],price_text=str(row['price'])+' '+str(row['currency'])))
                            if row['delivery_bg']=='confirmed':
                                row['delivery_evidence'] = row['url']+'#delivery-badge' if source=='olx' else cfg.get('delivery_evidence','')
                                row['delivery_verified_on'] = stamp[:10] if source=='olx' else cfg.get('delivery_verified_on','')
                            row['status'],row['reason'] = match(row,model)
                            if row['status'] != 'rejected':
                                rows.append(row)
                        job['pages'] += 1
                        if args.fixtures:
                            next_url = None
                        if next_url and urlsplit(next_url).hostname not in cfg['hosts']:
                            raise SourceError('pagination_host_changed')
                        url = next_url
                    job['truncated'] = bool(url)
                    job['rows'] = len(rows)
                    if job['truncated']:
                        job['detail'] = 'page_limit_reached; bounded sample'
                except (SourceError, ValueError) as exc:
                    detail = str(exc)[:160]
                    job.update(status='error',detail=detail,rows=len(rows),failure_category=getattr(exc,'category','parser'))
                    job['attempts'].extend(getattr(exc,'attempts',[]))
                    # Keep diagnostic rows but never summarize a partially failed query.
                    if detail != 'fixture_unavailable' and not detail.startswith(('parser_', 'assisted_', 'visual_')):
                        circuit = detail
            rows = list({(r['url'],r.get('merchant','')):r for r in rows}.values())
            job['rows'] = len(rows)
            all_rows.extend(rows)
            run['jobs'].append(job)
            print(f"{source} {model['id']}: {job['status']} ({job['rows']}) {job['detail']}",flush=True)
        browser.close()
    # Count unique daily observations, never promoted-card duplicates.
    all_rows = list({(r['source'],r['model_id'],r['url'],r.get('merchant','')):r for r in all_rows}.values())
    save(db,all_rows)
    run['finished_at'] = datetime.now(timezone.utc).isoformat()
    run['successful_jobs'] = sum(j['status']=='ok' for j in run['jobs'])
    run['failed_jobs'] = sum(j['status'] not in ('ok','disabled','not_configured') for j in run['jobs'])
    run['collected_rows'] = len(all_rows)
    run['health'] = 'ok' if run['failed_jobs']==0 and run['successful_jobs'] else 'partial' if run['successful_jobs'] else 'failed'
    run['accepted_rows'] = sum(r['status']=='accepted' for r in all_rows)
    run['review_rows'] = sum(r['status']=='review' for r in all_rows)
    run['methods'] = {m:sum(r.get('extraction_method')==m for r in all_rows) for m in sorted({r.get('extraction_method') for r in all_rows})}
    snapshot = Path(args.database).absolute().parent/'runs'/run_id
    summaries = export(db,catalog,snapshot,run)
    # Markdown report is readable directly in GitHub, no hosting setup required.
    report = ['# Component price tracker','',f"Run: {stamp} | Mode: {run['mode']} | Health: **{run['health']}**",'',
              'Prices in EUR. Used prices are asking prices, not completed sales. Shipping is excluded unless known.','',
              '| Component | Condition | Market | Samples | Median EUR | Confidence |','|---|---|---|---:|---:|---|']
    for s in summaries:
        if s['sample_count']:
            report.append(f"| {s['name']} | {s['condition']} | {s['market']} | {s['sample_count']} | {s['median_eur']} | {s['confidence']} |")
    if not any(s['sample_count'] for s in summaries):
        report.extend(['','No verified, delivery-confirmed component offers in this run. See listings.csv and review.csv for observations requiring review.'])
    report.extend(['',f"Collected: {run['collected_rows']} unique observations; accepted: {run['accepted_rows']}; review: {run['review_rows']}.",''])
    for j in run['jobs']:
        if j['status'] not in ('ok','not_configured') and not j['detail'].startswith('source_circuit_open:'):
            report.append(f"- {j['source']}: {j['detail']}")
    report.extend(['','[Source status](source_status.csv) · [All listings](listings.csv) · [Review queue](review.csv) · [Price history](history.csv)','',
                   'The catalog and page limits define coverage. This is a sample, not an exhaustive crawl. Failed/old observations do not feed current summaries.'])
    (snapshot/'README.md').write_text('\n'.join(report)+'\n')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('\n'.join(report))
    backup(db,snapshot/'prices.sqlite')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir() if p.is_file()}
    (snapshot/'manifest.json').write_text(json.dumps(dict(run_id=run_id,sha256=hashes),indent=2))
    point_output(args.output,snapshot)
    print('Report: '+str(Path(args.output).absolute()/'README.md'),flush=True)
    db.close()
    return 0 if run['successful_jobs'] else 2


def main():
    args,catalog,sources,selected = arguments()
    try:
        with lock(args.database):
            return collect(args,catalog,sources,selected)
    except (RuntimeError,ValueError,OSError) as exc:
        print(str(exc),flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
