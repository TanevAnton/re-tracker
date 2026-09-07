"""Local Apple Vision OCR; strict card-level parsing, never a page-wide price guess."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
from .parsers import listing, canonical
from .http import SourceError


def clean(value, limit=200):
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[redacted]', str(value))
    value = re.sub(r'(?<!\w)(?:\+359|00359|0)[\d ()-]{8,}(?!\w)', '[redacted]', value)
    return ' '.join(value.split())[:limit]


def read_image(data, executable):
    if not Path(executable).is_file():
        raise SourceError('visual_runtime_missing')
    with tempfile.TemporaryDirectory(prefix='retech-ocr-') as tmp:
        path = Path(tmp)/'card.png'
        path.write_bytes(data)
        try:
            result = subprocess.run([str(executable), str(path)], capture_output=True, text=True, timeout=30, check=True)
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, ValueError) as exc:
            raise SourceError('visual_ocr_failed') from exc


def parse_card(lines, url, source, *, title=None, method='visual_ocr'):
    """One observed link/region only. OCR rows require review even at confidence 1."""
    if not canonical(url):
        raise ValueError('missing_title_or_url')
    if not title:
        # Only component-like lines; ambiguous/multiline identity needs assistance.
        candidates = [x['text'] for x in lines if re.search(r'\b(?:RTX|GTX|RX|Ryzen|Core|Kingston|Corsair|Samsung|GeForce)\b', x['text'], re.I)]
        if len(candidates) != 1:
            raise SourceError('assisted_identity_required')
        title = candidates[0]
    prices = [x for x in lines if re.search(r'\d[\d .,]*\s*(?:€|EUR|лв\.?|BGN)\b|\d[\d .,]*\s*€', x['text'], re.I)]
    # A single row may show both currencies. Several monetary lines can mean
    # installments/discounts/delivery: retain unknown instead of picking one.
    price_text = prices[0]['text'] if len(prices) == 1 else ''
    reason = 'visual_requires_review' if method == 'visual_ocr' else 'rendered_text_requires_review'
    try:
        r = listing(clean(title), url, price_text)
    except ValueError:
        r = dict(title=clean(title),url=canonical(url),price=None,currency=None,price_eur=None,
                 condition='unknown',availability='unknown',shipping_eur=None,delivery_bg='unknown',price_kind='offer',merchant='')
        reason = 'ambiguous_or_missing_price'
    confidence = min((float(x.get('confidence', 0)) for x in lines), default=0)
    r.update(extraction_method=method, extraction_confidence=round(max(0,min(1,confidence)),3),
             extraction_review=reason, evidence=dict(title=clean(title),price_text=clean(price_text,100)))
    if source == 'olx': r['price_kind'] = 'asking'
    # Never infer condition, availability, shipping or delivery from the source name.
    return r
