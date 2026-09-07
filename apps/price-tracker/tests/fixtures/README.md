# Parser fixtures

Small excerpts of public DOM captured on 2026-09-07:

- `olx.html`: https://www.olx.bg/ads/q-rtx-3060/
- `desktop.html`: https://desktop.bg/search?q=Ryzen%205%207600

Images, SVGs, forms, buttons, public seller identity blocks and location/date blocks were removed. Price, currency, condition, model titles, product links, availability microdata and delivery badges remain for parsing tests. These are historical test inputs, never production feeds. Pazaruvaj JSON-LD tests are synthetic and do not claim live parser verification.

Ardes fixture: minimal Product/Offer JSON-LD plus the visible external-supplier stock caveat from the mapped Ryzen 5 7600 BOX page, checked locally 2026-09-07. Reviews, photos and contact details were discarded. The schema/visible-stock conflict is deliberate regression evidence. Browser canvas/OCR tests synthesize their own content and never request a marketplace.
