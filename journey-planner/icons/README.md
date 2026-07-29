# Journey design icons

`render_journey_design.py` draws a built-in line glyph for every activity
family, so the boards work with this folder empty. Drop a file here to override
one — that is the whole customisation step, no code change:

    journey-planner/icons/<family>.png     (or .webp)

- Square, transparent background, ≥ 128×128 (it is drawn at ~62 px, downscaled
  with LANCZOS).
- The name must be the **family** key, not the wire activity name:
  `freespins.png` overrides `freespin_bonus`, `freespin`, `free_spins`, `fs`.

Families (one icon each):

| file | covers |
| --- | --- |
| `source.png` | generic entry |
| `segment.png` | player segment source |
| `api.png` | `external_system_source` — wheel/API entry |
| `csv.png` | CSV upload source |
| `registration.png` | registration source |
| `promocode.png` | promo-code entry |
| `promotion.png` | `promotion` activity |
| `promo_page.png` | promo page object |
| `wheel.png` | Fortune Wheel / randomizer |
| `scratch.png` | scratch card |
| `deposit.png` | deposit condition |
| `freespins.png` | `freespin_bonus` |
| `casino_bonus.png` | `casino_bonus_v2` |
| `freebet.png` | sport free bet |
| `sport.png` | other sportsbook rewards |
| `gift.png` | physical / manual prize |
| `wait.png` | `wait_interval`, `wait_date` |
| `notification.png` | `notification_center`, pop-up, push |
| `email.png` | email message |
| `sms.png` | SMS message |
| `comms.png` | comms journey |
| `drip.png` | choosable flow |
| `split.png` | A/B split |
| `connector.png` | `campaign_connector`, prize routing |
| `end.png` | `end_of_journey` |
| `unknown.png` | anything unrecognised |

The accent colour of a card comes from `FAMILIES` in the renderer, not from the
icon, so a monochrome icon in the family colour (or plain dark) fits best.
