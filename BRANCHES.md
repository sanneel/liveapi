# Branches

Working notes on the branch list, so cleaning it up does not mean re-deriving
what each branch was for. Counts are against `main` at `d86f15c` (2026-07-29).

Refresh with:

```bash
git fetch origin --prune
for b in $(git ls-remote --heads origin | awk '{print $2}' | sed 's|refs/heads/||'); do
  sha=$(git ls-remote origin "refs/heads/$b" | awk '{print $1}')
  printf '%-50s ahead=%-4s behind=%-4s\n' "$b" \
    "$(git rev-list --count origin/main..$sha)" "$(git rev-list --count $sha..origin/main)"
done
```

## Naming

Prefix by intent, not by who made the branch. Nine of nineteen branches
currently start with `claude/`, so the prefix sorts nothing and says nothing
about whether the branch is safe to delete.

| Pattern | For | Example |
| --- | --- | --- |
| `feat/<area>-<what>` | new capability | `feat/sport-wof-per-wheel-copy` |
| `fix/<area>-<what>` | defect repair | `fix/promotions-copy-button` |
| `capture/<promo>` | a HAR-derived generator | `capture/tournament-jbcl` |
| `chore/<what>` | deps, CI, cleanup | `chore/dependabot-batch-july` |
| `spike/<what>` | explicitly disposable | `spike/figma-slot-export` |

`<area>` is one of the real top-level areas: `cloner`, `planner`, `admin`,
`render`, `parser`. Keep a random suffix only to break a genuine collision.

## Active — land these

Both are 0 behind `main` and carry real work.

| Branch | Ahead | Notes |
| --- | --- | --- |
| `claude/har-automation-liveapi-ujl76c` | 18 | Sport WOF rewrite, tournament comms split into `tournament_comms_base.py` + per-brand, three new test scripts |
| `claude/ai-planner-chain-composer` | 16 | Comms builder tab, composer email authoring, `comms_builder.py` |

**These two conflict with each other.** Both contain the same four sport-comms
commits (`592882c`, `ffcc255`, `aac9f1c`, `3b061ac`) and both add
`journey-cloner/sport_comms_campaign.py` — at 1028 lines on `har-automation` and
748 on `ai-planner-chain-composer` — plus the same four
`templates/sportcomms/*.json` captures. The two copies have diverged; a human
has to decide which is the truth before either merges. See the analysis at the
bottom of this file.

Suggested order: settle `sport_comms_campaign.py`, land `har-automation`, then
rebase `ai-planner-chain-composer` onto the result.

## Merged — safe to delete now

| Branch | Notes |
| --- | --- |
| `claude/tournament-comms-backoffice-2ti5za` | 0 ahead, fully contained in `main`. Nothing to preserve. |

Turn on GitHub's *Automatically delete head branches* so this stops recurring.

## Stale — archive then delete

All are far enough behind that rebasing is a rewrite, not a refresh. **Tag before
deleting** so the commits stay reachable:

```bash
git tag archive/<name> <sha> && git push origin archive/<name>
git push origin --delete <branch>
```

None of these has an open pull request, so deleting them closes nothing.

| Branch | Ahead | Behind | Head | Verdict |
| --- | --- | --- | --- | --- |
| `claude/journey-planner-mvp-test-882ubc` | 1 | 31 | `c880b58` | **Delete, no tag needed.** Its one commit has the same subject as `aca87f9`, already in `main`. |
| `claude/compose-recipe-template-r5f638` | 2 | 87 | `22f5ad5` | Tag. Early recipe-engine work, superseded by the composer in `main`, but the recipe KB commit may still be worth reading. |
| `claude/slot-card-gif-links-k5jmog` | 8 | 111 | `73639c4` | Tag and delete. Slot-card reveal GIFs. |
| `claude/jugabet-two-spin-gif-oejask` | 7 | 111 | `9e0c134` | Tag and delete. Slot GIF text placement. |
| `claude/journey-cloner-card-layout-3waah1` | 2 | 145 | `832c9e9` | Tag and delete. Cube mobile layout + GIF face. |
| `feat/vip-campaign-theme` | 4 | 164 | `ba6274b` | Tag and delete — but see below. |
| `claude/journey-cloner-duplicate-id-w18h37` | 4 | 182 | `25cc968` | Tag and delete. Slot GIF serving; two commits are bare "Add files via upload". |

### `feat/vip-campaign-theme`, checked

Its name suggests a campaign theme; it is actually four unrelated commits. The
two journey-cloner ones look important because they touch a stated
non-negotiable ("regenerate every id, per draft"), but both are **already
covered in `main` under different names**:

- `1386553` "regenerate internal activity ids per clone" → `main` has
  `create_journeys.regenerate_internal_ids()`, remapping every id through
  `uuid.uuid4()`.
- `d53fa30` "reserve fresh promotionDisplayId per clone" → `main` takes the
  opposite and safer approach in `strip_promotion_display_ids()`: drop the id
  entirely and let the backoffice mint it server-side.

Its other two commits are cube-related (`bada9a6` excluding long-finished
matches from cube slots, `ba6274b` a cache-busted cube URL for email). **Confirm
those two are in `main` before deleting** — they were not checked here.

## Bot branches

Eight open dependabot PRs, 87–169 commits behind. They are left alone
deliberately: closing a dependabot PR tells it not to offer that version again,
which is a dependency-policy decision rather than cleanup.

| PR | Bump | Note |
| --- | --- | --- |
| #9 | requests 2.32.3 → 2.34.2 | **Already applied to `main` by hand.** Close it. |
| #7 | actions/checkout 4 → 7 | batch |
| #25 | actions/setup-python 5 → 7 | batch |
| #10 | python-multipart 0.0.29 → 0.0.32 | batch |
| #11 | slowapi 0.1.9 → 0.1.10 | batch |
| #12 | pyotp 2.9.0 → 2.10.0 | batch |
| #13 | fastapi 0.136.1 → 0.137.2 | batch |
| #26 | tailwindcss 3.4.19 → 4.3.3 | **major** — review separately, v4 is a rewrite |

Group the six routine ones into a single monthly `chore/deps` branch and verify
with `./scripts/bootstrap.sh` before merging.

## The `sport_comms_campaign.py` collision

The one item here that cannot be resolved mechanically.

```
main (d86f15c)
  ├── claude/har-automation-liveapi-ujl76c        sport_comms_campaign.py  1028 lines
  └── claude/ai-planner-chain-composer            sport_comms_campaign.py   748 lines
                    ▲
        both contain 592882c ffcc255 aac9f1c 3b061ac
        both add the same 4 templates/sportcomms/*.json captures (16k+ lines)
```

They forked at `3b061ac` and neither is a superset — 14 commits one way, 12 the
other. Merging will conflict across the whole file plus every shared capture.

**Recommendation: take `har-automation`'s copy as the base.** Compared function
by function (12 shared, 6 differing) it is the more developed line, and the
difference is structural rather than cosmetic:

| | `har-automation` | `ai-planner-chain-composer` |
| --- | --- | --- |
| `verify` | 312 lines | 248 lines |
| `prepare` | 152 lines | 96 lines |
| `json_escape` | 19 lines | 4 lines |
| extra helpers | `_comms_node`, `_storages`, `set_channel_copy`, `set_display_data`, `set_sms_text` | `replace_lang` |

The five extra helpers are the reason. `set_channel_copy` writes each node's
copy into **both** storages via `_storages`, matches fields by a base+language
regex instead of hardcoded names, skips `%placeholder%` values because those are
template references rather than copy, and **returns a write count**. That last
point matters beyond this file: the identical missing-return-count bug in
`tournament_pmcl_campaign.set_var` shipped the captured campaign's copy
alongside the new copy, and had to be retrofitted with `require_var` in
`2c480d8`. `har-automation` already got this right structurally.

`ai-planner`'s `replace_lang(text, captured, en, es)` is the older approach —
find the captured string, substitute it — which is exactly the fragile path
`set_channel_copy` replaces. Nothing in it appears to survive the comparison.

So: base on `har-automation`, then replay only `ai-planner`'s comms-builder work
(`comms_builder.py`, the builder tab, the composer's email authoring) on top,
which does not overlap this file. Do not let git interleave the two versions —
an auto-merged generator that builds a wrong payload is the precise failure this
repo's refusals exist to prevent.
