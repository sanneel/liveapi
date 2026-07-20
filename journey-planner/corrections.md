# Corrections — operator-taught fixes

One fix per line, newest at the bottom. Format each as: the wrong assumption →
the right rule. These are appended to the planner's system prompt and OVERRIDE
the knowledge base when they conflict. Add a line the moment you learn something
— no need to restructure the main KB.

- Casino "Cashout" / limit value N → `releaseLimitMultiplier: N` with `limitType: "multiplier"` (it's a multiplier, not a bonus amount).
- Casino "Contribution" N → the wagering contribution rate; set it ONLY when `withWagering` is true.
- A Randomizer that has its own `urlShortName` needs NO separate Promo Page — the wheel URL is itself the landing page.
- KB §5/backlog marks these as uncaptured, but they ARE in the templates and can be built: `email_engagement_split`, `random_split`, `sport_bonus`, `registration`.
- A composed (not cloned) journey is proven to render + save in REA — see journey-cloner/COMPOSER_RULES.md for the canvas rules (position+positionAbsolute, one node schema per recipe, de-nest parentNode, start trigger).
