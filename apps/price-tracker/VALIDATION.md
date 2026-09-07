# Local validation — 2026-09-07

## Repository and preservation

Inspected the original README, all tracker modules, source/catalog configuration, Google Apps Script, GitHub workflow, fixture suite, and `origin/price-data` before changing them. The baseline was commit `9e2e43b` with 126 models in 19 categories and 13 passing tests. Only `TanevAnton/re-tracker` was changed.

The restored data commit was `b2e85fa63d45b1d8e1aae7a990cb176f8f8bd754`: a valid 143,360-byte SQLite database containing **zero observations and two run records**. Its original copy is retained under `.local/backups/`. The local database now preserves those original runs, new observations and successive same-day observation events. Code was never checked out over the data branch.

The isolated environment uses macOS 26.3.1 arm64, Python 3.13.13, Playwright 1.55.0, installed Google Chrome and a compiled Apple Vision helper. `doctor` successfully launched the actual isolated browser. No paid API key was configured or used. Interactive Codex Chrome accessibility/computer-use was inspected separately and is not a scheduled-runtime dependency.

## Live network/browser evidence

Small end-to-end scope: catalog model `ryzen-5-7600`, one page, four configured sources.

| Source | Actual outcome |
|---|---|
| Desktop | HTTP parsed the search and saved one accepted observation. Latest scheduled observation: AMD Ryzen 5 7600 MPK, EUR 189.00, new/in-stock, unknown shipping. |
| Ardes | Exact mapped Ryzen 5 7600 BOX URL returned EUR 222.99. Saved one review observation: condition unknown, external-supplier availability, shipping unknown. |
| OLX | `robots.txt` HTTP 403; no listing requests or browser collection attempted. |
| Pazaruvaj | Robots fetch succeeded and disallows the configured `?st=` search. Terms require written permission to use content. The collection policy returns `permission_required`; no workaround attempted. |

Latest verified launchd run: `56436f69-34de-4101-a3bc-3bb0e46d364a`, completed **2026-09-07 14:46:58 UTC**, process exit **0**, health **partial**, **two unique live observations: one accepted and one review**, both HTTP. The accepted sample is one, so it is **not eligible for a price benchmark recommendation** under the existing sample-count rule.

A separate **real isolated browser** check of Desktop's same search returned **19 rendered cards and one exact accepted match**. This was a browser adapter check, not 19 stored observations, and did not inflate the production database. Ordinary Chrome accessibility also exposed the product/price. HTTP already worked, so forcing screenshot interpretation of this live page was unnecessary.

Ardes enabled only after its exact product page was validated and a regression test was added for the misleading structured stock flag. Other Ardes models remain `not_configured`, not successful empty searches. Pazaruvaj and OLX need approved source access or authorized manual/feed input before they can contribute data.

## Local scheduling

The first launchd attempt failed because macOS denied access to Documents (`Operation not permitted`, exit 126). Moved the same repository to `~/Developer/re-tracker`, left a symlink at the original project path, rebuilt the virtual environment and reinstalled the job. No system access permission was broadened.

The second **actual launchd invocation**, through the installed plist, completed the four-source live CPU run with exit 0 and wrote both the report snapshot and `.local/last-scheduled.json`. The smoke-test model override was then archived; future runs use all 126 models, one page per query. Daily time is 07:23 in the Mac's local timezone. Calendar sleep coalescing behavior was verified against the installed `launchd.plist` manual. The job does not run while powered off or logged out and does not retry on network reconnect.

Overlap locking, atomic report-pointer switching and invalid-restore preservation are covered by tests. Each collection has a three-hour wrapper time limit, durable per-run logs and a completion record. History/snapshots are retained. Only the latest 30 dated runtime logs are retained automatically.

After this local scheduler succeeded, the GitHub workflow was changed to **CI only**, removing both its cron and its collection/data-publishing job. No local export was published to the public `price-data` branch; the explicit publication preview succeeded and printed the exact snapshot hashes.

## Tests versus live evidence

`TRACKER_BROWSER_TESTS=1 ./trackerctl test`: **38 passing tests**, including the original 13. The normal CI command runs 36 tests and skips the two opt-in browser tests.

Coverage includes:

- HTTP-first behavior, rendering/parser fallbacks, plain 403 gating and terminal policy/robots/login/challenge/rate-limit failures.
- Robots wildcard/query rules and allow precedence.
- Actual Chrome DOM parsing of local fixtures, and a synthetic canvas rendered to a screenshot, read by the real Apple Vision OCR runtime.
- Unknown/ambiguous prices and shipping, review-only OCR, RAM kit sizes, storage capacity and variants.
- Ardes's visible supplier caveat taking precedence over Schema.org availability.
- Deduplication, same-day history events, failed/stale-query exclusion and separate retail/classified market groups.
- Safe database merge, corrupt input rejection, overlapping-process lock, snapshot checksums and atomic report selection.
- Manual/feed/assisted import validation, confidence, fixture/live database separation and fixture publication rejection.

The standalone fixture collector produced **two fixture observations** in `.local/fixtures/`, never in live data. These are regression artifacts, not live offers. No live visual prices were collected; screenshot capability was verified with synthetic fixtures. `node --check` validated Apps Script syntax; no live spreadsheet was edited or refreshed.

## Remaining dependencies and operational limits

- OLX: readable source policy and permitted data access, or authorized manual/feed data. No market-wide API access was assumed.
- Pazaruvaj: source permission/licensed data access; browser automation cannot override its restrictions.
- Ardes: one mapped product pilot; more exact product mappings and condition/stock evidence are needed for broader coverage.
- Semantic visual interpretation beyond bounded OCR: an interactive assisted session. There is no unattended paid vision API integration.
- Google Sheets: replace any installed Apps Script with this version; use explicit approved publication for local results. Old public exports will become stale without publication.
- Monitoring: daily GitHub run monitors must switch to local completion/source-health checks. No matching local Codex automation was found. Other cloud/Claude monitors were not visible here.
- The full 126-model daily crawl was not run as part of the bounded live check; category/catalog support is broader than the live evidence above.
