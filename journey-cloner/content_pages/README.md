# Content pages — standalone promo pages pasted into the backoffice

A **content page** is one self-contained blob (style + markup + script) that an
operator pastes into a promo's rich-text content field. It renders for every
player and talks to the **client** promo API with the player's own session, so
it can read that player's turn state and spend a turn. The generators in
`journey-cloner/` build *drafts*; these pages are what the player touches.

Nothing here publishes anything. Pasting a page into a draft is still a draft.

## What lives here

| File | What it is |
| --- | --- |
| `giro_ganador_diario.html` | Giro Ganador Diario — 3-reel slot, 4 prizes, one spin per day |
| `preview.py` | Wraps a blob in a doctype shell so it opens in a browser |

## The five rules a blob must follow

These are not style preferences. Each one is a way the paste breaks.

1. **No `<` in the script.** CKEditor can escape the body on a round-trip, and
   `&lt;` inside a `<script>` is a syntax error. Use `i !== n` and `a > b`,
   never `a < b`; write `for (i = 0; i !== n; i = i + 1)`.
2. **No `&` anywhere.** Same reason — `&&` becomes `&amp;&amp;`. Use nested
   `if`s. `||` is fine (no ampersand). This is also why the font `@import`s are
   split one per family: a single query parameter each means no separators.
3. **The script writes no markup.** No `innerHTML` with tags — that would need
   `<`. Build nodes with `createElement` and set `className`.
4. **No SVG.** The proven-safe pages use zero SVG because the editor may strip
   it. The slot symbols are plain `div`s with gradients, `clip-path` and a
   `::before` glyph.
5. **Scope everything and `!important` everything** under the page's own root
   class, so host CSS cannot reach in. Put `&nbsp;` inside decorative empty
   elements (with a `font-size:0` helper class) so the editor does not drop them.

There is a sixth rule that is easy to get backwards: **do not put `!important`
on any property the script writes inline or a keyframe animates.** Author
`!important` beats both inline styles *and* CSS animations, so
`transform: translateY(0) !important` on a reel silently freezes it — the
inline transform is set, the computed value stays `0`, and nothing moves.

Verify a blob before pasting:

```bash
python3 - <<'PY'
import io, re
s = io.open('giro_ganador_diario.html', encoding='utf-8').read()
js = re.search(r'<script type="text/javascript">(.*)</script>', s, re.S).group(1)
print("script  '<':", js.count('<'), " '&':", js.count('&'))       # must be 0 0
print("stray &:", [l for l in s.split('\n') if '&' in l and '&nbsp;' not in l])
PY
```

## Previewing locally

```bash
python3 preview.py giro_ganador_diario.html --mock   # offline simulation
python3 preview.py giro_ganador_diario.html          # hits the real API
```

The blob stays the source of truth — `preview.py` only adds the doctype shell,
so the preview cannot drift from what ships. `--mock` flips `data-mock` to
`"1"`, which swaps the network layer for an in-memory fake and shows a loud
`SIMULACIÓN` banner. The simulation keeps its state in memory, never in
`localStorage`/`sessionStorage`, so a reload restarts the demo and no
"local truth" code path exists in the shipped file at all.

## Turn state comes from the platform, every load

The rule for any per-day promo: **the page never decides whether a turn is
available.** It asks. `giro_ganador_diario.html` does this by reading one
randomizer per promo day (`data-slugs`), because a Casino WOF randomizer has
`randomizerShotPolicy: "Once"` — one turn ever, not one per day — and
`randomizer_campaign.py --dates D1 D2` already creates one randomizer per date
with its own `04:02 -> 03:58` window. The window is what enforces "one per
day", server-side.

Consequences worth knowing before you debug something that is not broken:

- On day 1, day 2's randomizer usually **404s** — it does not exist yet. That
  is the normal case, not an error: the day card reads *Pendiente* and the page
  stays usable.
- A second spin only appears if the platform really has another open turn. In
  production that means **tomorrow, after a reload**. The `--mock` simulation
  deliberately opens both days at once so one sitting can exercise both spins
  and all four prizes.
- A retry after a failure re-`PUT`s the **same** `playerTurnId`. That
  idempotency is the only thing standing between a flaky network and a second
  prize.

## Prize copy is addressed by POSITION

`data-prize-*` maps are keyed by the prize's index in the randomizer's
`prizes[]` (`"0"`..`"3"`), or by an exact `prizeId`. Positions survive
duplicating a randomizer for a new date; ids do not. The Casino WOF order is
fixed by the captured template and cannot be reordered:

| Pos | Prize | Weight |
| --- | --- | --- |
| 0 | Free spins with a deposit | 60 |
| 1 | Casino bonus with a deposit | 35 |
| 2 | Free spins, no deposit | 5 |
| 3 | Casino bonus, no deposit | 0 |

The page reads `prizeId || id` when indexing, because the backoffice template
calls the field `id` while the client config returns `prizeId`. Get that wrong
and *every* prize falls through to the generic copy with nothing failing loudly.

Two deliberate refusals, both from
[`../../CLAUDE.md`](../../CLAUDE.md)'s "a refusal is the feature":

- A prize with **no configured copy** never gets an invented amount. It shows
  the one thing that is certainly true ("your prize is assigned") and logs a
  console warning naming the id and position.
- Copy for a prize whose amount is **not defined in the brief** states no
  figure at all. Position 3 is like this today (weight 0, no value on the
  sheet), so its copy talks about the bonus being credited and quotes no
  number. If it is ever given a weight, put the real strings in first.
