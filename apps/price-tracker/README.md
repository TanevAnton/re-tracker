# Re-Tech component price tracker

Bulgaria PC-component observations for future configurator inputs and used-component research. This application writes only its own database and reports. It never changes store prices, configurator prices, or valuation formulas.

## Local setup and commands

Python 3.12+ is required (this Mac uses isolated Python 3.13.13). Google Chrome is the default browser runtime. On macOS, Xcode Command Line Tools provide `swiftc`, which compiles the free, local Apple Vision OCR helper. No paid vision service, browser account or API key is required.

```bash
cd ~/Developer/re-tracker/apps/price-tracker
./trackerctl setup                           # venv + pinned dependencies + local OCR helper
./trackerctl doctor                          # actual browser launch, runtime inventory
./trackerctl restore                         # fetch price-data; validate, back up, merge SQLite
./trackerctl test                            # offline unit/fixture tests
TRACKER_BROWSER_TESTS=1 ./trackerctl test     # include actual Chrome + screenshot/OCR fixture tests
./trackerctl collect --model ryzen-5-7600 --max-pages 1
./trackerctl collect                         # all configured models, max two pages per query
./trackerctl report                          # print latest report and output location
open .local/output/README.md                 # or inspect CSV/JSON beside it
```

`TRACKER_PYTHON=/absolute/path/to/python3.12 ./trackerctl setup` chooses another compatible interpreter. On Linux, install a browser supported by Playwright and use `--browser-channel chromium` after `.venv/bin/python -m playwright install chromium`; Apple Vision and this scheduler are macOS-specific. Missing optional browser/OCR runtimes produce explicit source diagnostics. `--headed` shows the isolated browser if a fallback is needed; it does not bypass HTTP or policy checks.

The active checkout is `~/Developer/re-tracker`. The old `~/Documents/Claude/Projects/RE-Tech/re-tracker` is a symlink. A launchd test in Documents failed with macOS `Operation not permitted`; relocating this repository allowed scheduling without changing system access permissions.

All live databases, logs, source probes, fixture runs, snapshots and compiled helpers stay under ignored `.local/`. `.venv/`, `.env*`, secrets, images and browser profiles are also ignored. Runtime browser contexts are disposable and never attach to personal Chrome profiles or saved logins. Do not commit credentials or raw screenshots.

## Sources and access policy

Verified locally on 2026-09-07; technical reachability and permission are separate checks.

| Source | Local HTTP | Browser / visual | Default behavior |
|---|---|---|---|
| Desktop.bg | Search microdata works; one exact Ryzen 5 7600 MPK observation | Real isolated browser DOM verified (19 search cards, one exact match); screenshot OCR tested on synthetic content | Enabled. HTTP first, browser on rendering/parser errors or a plain 403 while browser access is verified |
| OLX.bg | `robots.txt` returns HTTP 403 | Not attempted after policy fetch failed | Unavailable for automation. Use an authorized manual observation or approved feed |
| Pazaruvaj.com | Robots explicitly disallows `/*?st=` search. Terms require written consent to use content | Never used to work around either restriction | `permission_required`; obtain source permission/approved data access before changing policy |
| Ardes.bg | One exact mapped Ryzen 5 7600 BOX product URL returns 222.99 EUR | Not needed in the live probe; generic JSON-LD fallback remains provisional | Enabled only for mapped product URLs. One observation in review; other models are `not_configured` |

Ardes's structured data says `LimitedAvailability`, but the visible page says **external supplier**, with a warning that stock may be absent. The adapter records `supplier_confirmation`; unknown condition is also retained. It does not mark that offer as verified in-stock. Search collection is not implemented for Ardes. Add exact URLs only after checking the product and adapter.

Sources and dated delivery references are in [sources.json](config/sources.json). [Pazaruvaj terms](https://www.pazaruvaj.com/static/usloviq_za_polzvane.html) require consent. [Desktop/Laptop terms](https://laptop.bg/pages/terms-and-conditions) restrict commercial reuse of content; review reuse rights before publishing. Delivery evidence: [Desktop nationwide delivery](https://laptop.bg/pages/delivery), [Ardes delivery terms](https://ardes.bg/polezna-informaciya/obshti-usloviya). An OLX ad needs its own delivery badge or other explicit evidence. No additional marketplaces were added.

The identifying user agent is `ReTechPriceTracker/2.0` with this repository URL. HTTP and browser document navigations use a source host allowlist, robots rules with wildcard/query support, and at least three seconds between requests. Redirect destinations are validated before browser navigation. Browser subresources load normally; third-party frames are blocked. There is no user-agent impersonation, stealth patching, session/cookie transfer, login automation, rate-limit retry or challenge solver.

Errors distinguish `robots_disallowed`, `robots_http_403`, `http_403`, `http_429`, network failure, `javascript_required`, `login_required`, `security_challenge`, `access_denied`, parser failures, policy restrictions and missing runtimes. Source-level failures open a circuit for the remaining models; a query-specific layout failure can leave other models usable. `source_status.csv` and `status.json` retain the attempted methods and root reason.

## Browser and visual collection

`tracker.collection` executes the fallback chain; it is not a documentation-only feature:

1. Permitted HTTP and source-specific structured parsing.
2. Real Playwright-controlled Chrome with a fresh isolated context and the same identifying agent.
3. Rendered DOM parsing, then card-scoped rendered text/accessibility labels.
4. A screenshot of an identifiable product-card region, read by local Apple Vision OCR.

The browser preserves listing links and bounded regions before trying OCR. Several monetary lines, uncertain identities, missing currency or unreadable prices are never guessed. OCR and generic rendered-text observations go to review even if OCR confidence is high. Raw crops are transient; stored evidence contains just a short sanitized title and price text, together with URL, UTC timestamp, extraction method and heuristic confidence.

If no reliable card/link region exists, the source reports `assisted_regions_required` or `assisted_identity_required`. Codex's browser accessibility and screenshot/computer-use tools were available in the interactive session. They are **not callable by launchd**. For such layouts, use an assisted session to inspect the visible product and enter an observation through the import interface. Stop for a source prohibition, inaccessible robots, login, access denial or challenge; assistance is not a policy bypass. Semantic interpretation beyond local OCR requires that assisted session; no paid vision API is wired in.

See [Playwright browser support](https://playwright.dev/python/docs/browsers) and [Apple Vision text recognition](https://developer.apple.com/documentation/vision/recognizing-text-in-images).

## Manual, assisted and approved-feed import

The executable import path takes a local JSON envelope. It performs no marketplace request and does not accept arbitrary precomputed normalized prices or accepted/rejected status. Supply only observations you are authorized to use; only a checksum of the authorization reference enters observation payloads; keep the original import file locally.

```json
{
  "mode": "live",
  "method": "manual",
  "authorization": "Reference to the permission or authorized observation",
  "observations": [
    {
      "source": "olx",
      "model_id": "rtx-3060-12gb",
      "url": "https://www.olx.bg/d/ad/REPLACE-WITH-ACTUAL-LISTING",
      "title": "REPLACE WITH EXACT VISIBLE TITLE",
      "observed_at": "REPLACE WITH UTC ISO TIMESTAMP",
      "price": null,
      "currency": null,
      "shipping_eur": null,
      "condition": "unknown",
      "availability": "unknown",
      "delivery_bg": "unknown",
      "delivery_evidence": "",
      "confidence": 0
    }
  ]
}
```

```bash
./trackerctl collect --import-file .local/import.json
# After reviewing the exact observations and evidence:
./trackerctl collect --import-file .local/import.json --approved-import
```

Methods are `manual`, `assisted_visual`, or `approved_feed` (a licensed API/feed export mapped to this schema). There is no guessed feed endpoint or claim that OLX's developer API supplies market-wide listings. Credentials or an approved endpoint would be needed for an unattended remote feed adapter. Imports default to review; approval cannot override missing prices, insufficient confidence, bad matches or unknown delivery. Unknown shipping remains `null`; explicit zero shipping is accepted only when supplied as observed evidence. Outdated observations are stored but excluded from current summaries. OLX is always labelled `asking`, including new items.

## Matching and data quality

The catalog has **126 starter models across 19 categories**, not exhaustive product coverage. Categories include GPU, CPU, motherboard, RAM, SSD, HDD, PSU, case, CPU cooler, AIO, case fan, network card, sound card, optical drive, monitor, keyboard, mouse, headset and UPS. Additional categories work through required/excluded patterns; exact URLs and optional `mpn` let you tighten variants. Model IDs are stable. Do not interpret a supported category as complete coverage.

GPU chip/suffix and VRAM must agree; CPUs preserve suffixes such as X/X3D/F/K. General models are component-family observations, not exact board partner MPNs or warranty-equivalent quotes; use `mpn` for that stricter match. RAM catalog entries explicitly require 2x16GB or 2x8GB kits. Storage capacity and optional variants are checked. Existing required/excluded patterns remain valid. Missing kit size, uncertain variants, bundles, stock, condition or delivery go to review; broken/wanted ads and full systems are excluded.

Retail and classified asking prices have separate `market` groups, and each has separate new/used condition rows. Join summaries on **`model_id`, `condition`, `market`**. The old schema joined on two fields; consumers need the third. Shipping and prices are never defaulted to zero. EUR normalization retains original currency/amount and historical BGN conversion at 1.95583. Asking prices are not completed sales.

Only accepted listings seen in the current successful query within 36 hours enter summaries. Partial query failure removes that query from the current benchmark; historical observations survive. Source outages never imply sales. URL and merchant deduplication prevent promoted listings from inflating samples. Three observations and the existing spread rule are required for `eligible_for_review`; that flag never authorizes repricing.

## Database, exports and publication

`./trackerctl restore` fetches `price-data` without switching the code branch. It validates SQLite, keeps the original remote database and a backup of the current local database, then merges without replacing local conflicts. Original observations and run records survive. Daily observations retain their existing unique key; the additive `observation_events` table also preserves successive changes within one day.

Every completed run writes `.local/runs/<run-id>/` with SQLite, CSV/JSON and a checksum manifest. `.local/output` switches to the completed snapshot atomically. Failed processes leave the last complete report in place. Check `status.json` and timestamps. Snapshots/history are retained; monitor disk use. Generated per-run logs retain the most recent 30 files.

| Artifact | Contents |
|---|---|
| `summary.csv/json` | Separate market/condition figures, sample counts and freshness |
| `listings.csv/json`, `review.csv` | Latest observations, provenance, evidence and review reasons |
| `history.csv`, `events.csv`, `prices.sqlite` | Daily history and every recorded observation change |
| `source_status.csv`, `status.json` | Per-query methods, failures, coverage, counts and completion |
| `catalog.json`, `README.md`, `manifest.json` | Run catalog, human report and snapshot checksums |

Public GitHub reports are updated **only by explicit approval**:

```bash
./trackerctl publish                         # preview the exact run and file hashes
./trackerctl publish --approve-run RUN_ID    # publish that reviewed run to price-data
```

Publication checks mode, age, file integrity, repository identity and the restored remote data commit. A detached temporary worktree preserves both code and remote branch history; push never uses force. If `price-data` advanced, restore and collect a new snapshot before reviewing/publication. Only named export files are staged. Profiles, credentials, probe HTML, screenshots and raw authorization notes are not included. Authorization references are hashed before persistence. Review all exported titles, merchant identities, evidence and URLs before publishing. No exports were published during this implementation.

## Daily scheduling on macOS

```bash
./trackerctl schedule install --hour 7 --minute 23
./trackerctl schedule status
./trackerctl schedule run-now                # run the real launchd job now
./trackerctl schedule remove                 # unload; archive its plist
```

The installed LaunchAgent is `~/Library/LaunchAgents/bg.re-tech.price-tracker.plist`. It runs all configured catalog models at **07:23 in the Mac's local timezone**, with one page per query. An optional ignored `.local/schedule.json` may contain `{"model":"ryzen-5-7600","source":"desktop"}` for a bounded run. Remove it to return to the full catalog. The validation override was removed after the scheduler check.

A file lock shared by manual and scheduled collection prevents overlap on the same database. The wrapper limits a run to three hours and records the exit code, log path and finish time in `.local/last-scheduled.json`. Logs are in `.local/logs/`. Exit 0 means at least one job succeeded; **inspect health for partial source failures**. Exit 2 means all collection jobs failed. Exit 1 is a setup/input/overlap problem; 124 is a time limit. A source query with zero results is still a successful query, not a collection error.

The computer must be logged into this macOS user account. A missed calendar interval during sleep is coalesced into one run after wake; this job does not wake the computer. Shutdown/logout misses are not replayed at login (`RunAtLoad=false`). Offline runs record network failures and preserve previous history; there is no network reconnect retry. Run manually after reconnecting or wait for the next daily interval. Nothing silently publishes a local run.

After an actual successful launchd collection, the duplicate GitHub schedule and collection/publishing job were removed. GitHub Actions now runs offline CI tests only. Any external monitor watching daily Actions collections must instead check `.local/last-scheduled.json`, the source health and snapshot freshness. No matching Codex automation was found locally; other cloud/Claude monitors were not accessible to this repository check.

## Google Sheets

[Code.gs](sheets/Code.gs) still imports approved public GitHub exports. Paste it into a bound Apps Script project and run `setupPriceTracker` once. It refreshes its own `Prices`, `Source status`, and `Tracker run` tabs daily at 10:00 Europe/Sofia; personal notes belong elsewhere. The updated code resolves one `price-data` commit first so files cannot mix two publications. It validates freshness/live mode and guards against spreadsheet formulas from listing text.

The sheet does not read `.local/` directly. Run the explicit publish command after approving local results; otherwise the prior published data remains and the sheet's freshness check will flag stale results. Update any already installed Apps Script with this version. No live spreadsheet or its triggers was changed by this repository implementation.

## Fixture tests

```bash
./trackerctl collect --fixtures tests/fixtures --model rtx-3060-12gb --source olx
```

Fixtures use `.local/fixtures/` automatically, are marked `mode=fixture`, and cannot share a database with live runs or be published. Browser tests are synthetic/offline; real OCR success is capability evidence, not a collected live offer. See [VALIDATION.md](VALIDATION.md) for the actual check counts and limitations.
