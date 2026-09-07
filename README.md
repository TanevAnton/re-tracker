# Re-Tech component price tracker

Daily PC-component price observations from websites serving Bulgaria, for future configurator pricing and resale estimates. Python 3.12, GitHub Actions, SQLite history, and CSV/JSON exports.

- [Tracker documentation and setup](apps/price-tracker/README.md)
- [Latest reports and data](https://github.com/TanevAnton/re-tracker/tree/price-data)
- [Daily workflow and run status](https://github.com/TanevAnton/re-tracker/actions/workflows/price-tracker.yml)
- [Editable component catalog](apps/price-tracker/config/catalog.json)
- [Google Sheets import script](apps/price-tracker/sheets/Code.gs)

The workflow collects daily at **04:23 UTC** and stores results on the `price-data` branch. The starter catalog contains **126 models across 19 categories**; add exact models as needed. Retail and used prices remain separate, and OLX observations represent asking prices.

**Source access:** the last collection before this repository move returned HTTP 403 restrictions from OLX, Desktop.bg, and Pazaruvaj, with zero collected observations. Ardes is disabled. Check the latest report and source status before using any prices. Moving the repository does not resolve those source restrictions.

To run the existing tests:

```bash
cd apps/price-tracker
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

See the tracker documentation for collection commands, matching rules, source limitations, and Google Sheets setup.
