# Casino "Ace" free-spins email cards

A premium, reusable promo-card template (portrait 2:3, black matte + gold frame)
rendered to transparent PNGs for email. One card per suit; deposit is fixed per
suit, `{{FREE_SPINS}}` is the variable. Drop a 360×330 game PNG onto the black
artwork well in your email tool.

| Suit | Deposit |
|------|---------|
| ♥ hearts   | $10.000 CLP |
| ♦ diamonds | $20.000 CLP |
| ♣ clubs    | $30.000 CLP |
| ♠ spades   | $50.000 CLP |

## Files
- `casino_card.html` — the one-row deck template (keeps `{{FREE_SPINS}}`; for preview/editing).
- `render_cards.py` — single source of truth. Regenerates `casino_card.html` and renders the PNGs via headless Chromium.
- `out/*.png` — rendered transparent cards.

## Render
```bash
python render_cards.py --free-spins 50            # 4 PNGs into out/ with "50"
python render_cards.py --free-spins 100 --scale 3 # bigger, sharper
python render_cards.py --html                     # just rewrite the template
```
Needs a Chromium binary (uses PLAYWRIGHT_BROWSERS_PATH, or chromium on PATH).
