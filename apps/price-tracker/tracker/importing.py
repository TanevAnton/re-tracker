"""Manually reviewed or licensed feed observations, with no source network access."""
from datetime import datetime, timezone, timedelta
import json
import hashlib
import math
from pathlib import Path
from .http import Client
from .matching import match
from .parsers import money, canonical
from .visual import clean


def read_import(path, catalog, sources, run_id, approved=False):
    data = json.loads(Path(path).read_text())
    if data.get('mode') != 'live': raise ValueError('Import must explicitly declare mode=live; fixtures cannot enter the live database')
    method = data.get('method')
    if method not in ('manual','assisted_visual','approved_feed'):
        raise ValueError('Import method must be manual, assisted_visual or approved_feed')
    authorization = clean(data.get('authorization',''),160)
    if not authorization: raise ValueError('Import requires an authorization/permission reference')
    models = {m['id']:m for m in catalog}
    rows, jobs = [], {}
    for raw in data['observations']:
        source, model = raw['source'], models[raw['model_id']]
        cfg = sources[source]
        Client(cfg['hosts']).validate(raw['url'])
        stamp = datetime.fromisoformat(raw['observed_at'])
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc)+timedelta(minutes=5):
            raise ValueError('Observation requires a timezone-aware, non-future timestamp')
        r = dict(source=source, model_id=model['id'], category=model['category'], market=cfg['market'],
                 title=clean(raw['title']), url=canonical(raw['url']), observed_at=stamp.astimezone(timezone.utc).isoformat(),
                 run_id=run_id, mode='live', source_url=canonical(raw['url']), extraction_method=method,
                 extraction_confidence=raw.get('confidence',0), import_authorization_sha256=hashlib.sha256(authorization.encode()).hexdigest(),
                 condition=raw.get('condition','unknown'), availability=raw.get('availability','unknown'),
                 delivery_bg=raw.get('delivery_bg','unknown'), delivery_evidence=clean(raw.get('delivery_evidence',''),250),
                 shipping_eur=None, price_kind='asking' if source=='olx' else raw.get('price_kind','offer'),
                 merchant='' if source=='olx' else clean(raw.get('merchant','')),sku=clean(raw.get('sku','')))
        if not isinstance(r['extraction_confidence'],(int,float)) or not 0 <= r['extraction_confidence'] <= 1:
            raise ValueError('Confidence must be in [0,1]')
        if not r['title']: raise ValueError('Missing title')
        if raw.get('price') is None:
            r.update(price=None,currency=raw.get('currency'),price_eur=None)
        else:
            r['price'],r['currency'],r['price_eur'] = money(raw['price'],raw.get('currency'))
        if raw.get('shipping_eur') is not None:
            shipping = float(raw['shipping_eur'])
            if not math.isfinite(shipping) or shipping < 0: raise ValueError('Invalid shipping')
            r['shipping_eur'] = shipping
        if r['delivery_bg']=='confirmed' and not r['delivery_evidence']:
            r['delivery_bg']='unknown'
        r['evidence'] = dict(title=r['title'],price_text=clean(raw.get('price_text',''),100))
        if not approved or r['extraction_confidence'] < .9:
            r['extraction_review'] = 'import_requires_review'
        r['status'],r['reason'] = match(r,model)
        if r['status'] != 'rejected': rows.append(r)
        key=(source,model['id'])
        jobs.setdefault(key,dict(source=source,model_id=model['id'],status='ok',detail='import:'+method,pages=0,rows=0,truncated=False,attempts=[dict(method=method,outcome='reviewed' if approved else 'review')]))
        jobs[key]['rows'] += int(r['status']!='rejected')
    return rows,list(jobs.values())
