# Re-Tech component price tracker

Local daily PC-component price observations from websites serving Bulgaria. Source code lives in this dedicated repository; no Shopify, configurator or customer price writes.

- [Setup, commands, source policy and scheduling](apps/price-tracker/README.md)
- [Validation and handoff, 2026-09-07](apps/price-tracker/VALIDATION.md)
- [Catalog: 126 starter models across 19 categories](apps/price-tracker/config/catalog.json)
- [Published reports](https://github.com/TanevAnton/re-tracker/tree/price-data) — **only updated by an explicitly approved local publication**
- [CI tests](https://github.com/TanevAnton/re-tracker/actions/workflows/price-tracker.yml)

The local collector tries identifying HTTP, then a policy-permitted isolated Chrome session, then rendered text and local Apple Vision screenshot OCR. Uncertain extraction goes to review. Robots, login, challenges and explicit prohibitions stop collection; there are no CAPTCHA solvers, proxy rotations or browser-profile reuse.

On the configured Mac:

```bash
cd ~/Developer/re-tracker/apps/price-tracker
./trackerctl test
./trackerctl collect --model ryzen-5-7600 --max-pages 1
./trackerctl report
./trackerctl schedule status
```

Daily launchd collection is installed for **07:23 local time**. GitHub runs CI only. The original project folder contains a link to the repository; the checkout moved out of Documents because macOS denies launchd access there.

Live validation found **two unique observations** in the small four-source CPU check: Desktop.bg HTTP (one accepted), Ardes HTTP (one review). Desktop browser DOM also worked. OLX could not expose robots rules; Pazaruvaj requires permission and prohibits the configured search through robots. See the validation report for the distinction between live evidence and synthetic browser/OCR tests.
