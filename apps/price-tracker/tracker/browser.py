"""Real isolated Chromium runtime, independent of Codex's interactive tools."""
from pathlib import Path
from urllib.parse import urljoin
from .http import AGENT, SourceError
from .parsers import parse, page_problem
from .visual import parse_card, read_image


class Browser:
    def __init__(self, client, cfg, *, headed=False, channel='chrome', vision='.local/bin/vision-ocr'):
        self.client, self.cfg = client, cfg
        self.headed, self.channel, self.vision = headed, channel, vision
        self.runtime = self.browser = self.context = None

    def start(self):
        if self.context: return
        try:
            from playwright.sync_api import sync_playwright
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.launch(channel=self.channel or None, headless=not self.headed)
            self.context = self.browser.new_context(user_agent=AGENT, locale='bg-BG',
                    viewport={'width':1280,'height':900}, service_workers='block', accept_downloads=False)
        except Exception as exc:
            self.close()
            raise SourceError('browser_runtime_missing') from exc

    def get(self, source, url):
        self.client.check_robots(url)
        self.client.throttle(url)
        self.start()
        page = self.context.new_page()
        page.set_default_timeout(6000)
        policy_failure = []
        def route(request_route):
            request = request_route.request
            if request.is_navigation_request():
                try:
                    if request.frame != page.main_frame:
                        request_route.abort(); return
                    self.client.check_robots(request.url)
                except SourceError as exc:
                    policy_failure.append(exc)
                    request_route.abort(); return
            request_route.continue_()
        page.route('**/*', route)
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=25000)
            if policy_failure: raise policy_failure[0]
            problem = page_problem(page.content())
            if problem and problem != 'javascript_required': raise SourceError(problem)
            if response and response.status >= 400:
                raise SourceError(f'http_{response.status}', http_status=response.status)
            selector = self.cfg.get('card_selector', 'article')
            try:
                page.locator(selector).first.wait_for(state='visible',timeout=5000)
            except Exception:
                pass
            problem = page_problem(page.content())
            if problem and problem != 'javascript_required': raise SourceError(problem)
            return self.extract(page, source, page.url)
        except SourceError:
            raise
        except Exception as exc:
            if policy_failure: raise policy_failure[0]
            raise SourceError('browser_navigation_failed') from exc
        finally:
            page.close()

    def extract(self, page, source, url):
        attempts = []
        try:
            rows, nxt = parse(source, page.content(), url)
            for row in rows: row.update(extraction_method='browser_dom', extraction_confidence=0.95)
            return rows, nxt, [{'method':'browser_dom','outcome':'ok'}]
        except ValueError as exc:
            if not str(exc).startswith('parser_'): raise SourceError(str(exc)) from exc
            attempts.append({'method':'browser_dom','outcome':str(exc)})
        rows = []
        cards = page.locator(self.cfg.get('card_selector', 'article'))
        for i in range(min(cards.count(), 60)):
            card = cards.nth(i)
            if not card.is_visible(): continue
            links = card.locator(self.cfg.get('card_link_selector','a[href]'))
            if links.count() == 0: continue
            link = links.first
            target = urljoin(url, link.get_attribute('href') or '')
            self.client.validate(target)
            title = link.get_attribute('aria-label') or link.inner_text().strip() or None
            # Read rendered accessibility labels/text before spending OCR effort.
            visible = card.inner_text().strip()
            lines = [{'text':s,'confidence':0.7} for s in visible.splitlines() if s.strip()]
            try:
                row = parse_card(lines, target, source, title=title, method='browser_text')
                if row['price_eur'] is not None:
                    rows.append(row); continue
            except SourceError:
                pass
            if not self.cfg.get('visual', False):
                raise SourceError('visual_disabled')
            # Raw crop exists only in memory/temp directory. Only title/price
            # evidence survives. Do not capture whole pages, profiles or contacts.
            lines = read_image(card.screenshot(type='png', timeout=6000), self.vision)
            row = parse_card(lines, target, source, title=title)
            rows.append(row)
        if not rows: raise SourceError('assisted_regions_required', attempts=attempts)
        methods = sorted({r['extraction_method'] for r in rows})
        attempts.extend({'method':m,'outcome':'review'} for m in methods)
        nxt = page.locator('a[rel="next"], a[data-testid="pagination-forward"]')
        return rows, urljoin(url,nxt.first.get_attribute('href')) if nxt.count() else None, attempts

    def close(self):
        if self.context: self.context.close()
        if self.browser: self.browser.close()
        if self.runtime: self.runtime.stop()
        self.context = self.browser = self.runtime = None
