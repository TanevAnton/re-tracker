"""Identifying, rate-limited public HTTP with fail-closed robots and typed failures."""
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from protego import Protego

AGENT = 'ReTechPriceTracker/2.0 (+https://github.com/TanevAnton/re-tracker)'


def category(code):
    if code.startswith('robots_'): return 'robots'
    if code in ('automation_prohibited', 'permission_required', 'policy_unverified'): return 'policy'
    if code == 'login_required': return 'login'
    if code == 'security_challenge': return 'challenge'
    if code == 'access_denied': return 'access_restriction'
    if code == 'javascript_required': return 'rendering'
    if code.startswith('parser_'): return 'parser'
    if code.startswith('http_'): return 'http'
    if code.startswith(('browser_', 'visual_', 'assisted_')): return 'runtime'
    return 'network'


class SourceError(RuntimeError):
    def __init__(self, code, *, attempts=None, http_status=None):
        super().__init__(code)
        self.code = code
        self.category = category(code)
        self.attempts = attempts or []
        self.http_status = http_status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, hosts, delay=3.0, timeout=20):
        self.hosts = set(hosts)
        self.delay = max(3.0, delay)
        self.timeout = timeout
        self.robots, self.last, self.cache = {}, {}, {}
        self.opener = urllib.request.build_opener(NoRedirect)

    def validate(self, url):
        try:
            p = urlsplit(url)
            valid = p.scheme == 'https' and p.hostname in self.hosts and not p.username and not p.password and p.port in (None, 443)
        except ValueError:
            valid = False
        if not valid:
            raise SourceError('url_not_allowlisted')
        return p

    def throttle(self, url):
        p = self.validate(url)
        time.sleep(max(0, self.delay - (time.monotonic() - self.last.get(p.hostname, 0))))
        self.last[p.hostname] = time.monotonic()

    def request(self, url):
        self.throttle(url)
        req = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'text/html,text/plain', 'Accept-Language': 'bg,en;q=0.5'})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                data = r.read(8_000_001)
                if len(data) > 8_000_000:
                    raise SourceError('response_too_large')
                return data.decode(r.headers.get_content_charset() or 'utf-8', errors='replace')
        except urllib.error.HTTPError:
            raise
        except (OSError, TimeoutError) as exc:
            raise SourceError('network_unavailable') from exc

    def check_robots(self, url):
        p = self.validate(url)
        if p.hostname not in self.robots:
            try:
                body = self.request(f'https://{p.netloc}/robots.txt')
                if '<html' in body.lower() or '<!doctype' in body.lower():
                    raise SourceError('robots_unavailable')
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    body = ''
                else:
                    raise SourceError(f'robots_http_{exc.code}', http_status=exc.code) from exc
            self.robots[p.hostname] = Protego.parse(body)
        robot = self.robots[p.hostname]
        # Protego supports wildcard/query and $ rules that urllib.robotparser misses.
        if not robot.can_fetch(url, AGENT):
            raise SourceError('robots_disallowed')
        self.delay = max(self.delay, float(robot.crawl_delay(AGENT) or 0))

    def get(self, url):
        self.check_robots(url)
        if url in self.cache:
            return self.cache[url]
        try:
            body = self.request(url)
        except urllib.error.HTTPError as exc:
            from .parsers import page_problem
            body = exc.read(200_000).decode('utf8', errors='replace')
            problem = page_problem(body)
            if exc.code == 401: problem = 'login_required'
            raise SourceError(problem or f'http_{exc.code}', http_status=exc.code) from exc
        self.cache[url] = body
        return body
