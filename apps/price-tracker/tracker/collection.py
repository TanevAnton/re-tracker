"""Policy-aware HTTP -> rendered DOM/text -> local screenshot OCR selection."""
from .http import SourceError
from .parsers import parse

FALLBACK = {'javascript_required','parser_no_cards','parser_no_prices','parser_invalid_html'}


def browser_allowed(error, cfg):
    return bool(cfg.get('browser') and cfg.get('automation') == 'allowed' and
                (error.code in FALLBACK or
                 (error.code == 'http_403' and cfg.get('browser_access_verified') is True)))


def collect_page(source, url, cfg, client, browser):
    policy = cfg.get('automation', 'policy_unverified')
    if policy != 'allowed':
        raise SourceError(policy if policy in ('permission_required','automation_prohibited') else 'policy_unverified')
    attempts = []
    try:
        body = client.get(url)
        rows, nxt = parse(source, body, url)
        for row in rows: row.update(extraction_method='http',extraction_confidence=0.95)
        return rows,nxt,[{'method':'http','outcome':'ok'}]
    except (ValueError, SourceError) as exc:
        error = exc if isinstance(exc,SourceError) else SourceError(str(exc))
        attempts.append(dict(method='http',outcome=error.code,category=error.category,http_status=error.http_status))
    if not browser_allowed(error,cfg):
        error.attempts = attempts
        raise error
    try:
        rows,nxt,steps = browser.get(source,url)
        return rows,nxt,attempts+steps
    except SourceError as exc:
        exc.attempts = attempts+exc.attempts+[dict(method='browser',outcome=exc.code,category=exc.category,http_status=exc.http_status)]
        raise
