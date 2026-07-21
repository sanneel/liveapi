# Composer rules — synthesizing a journey canvas that the editor renders

Hard-won from building `compose_comms.py` and testing against the live REA
backoffice (a composed comms journey rendered + saved on 2026-07-20). These are
the rules a composer MUST follow to emit a `POST /journey-drafts` body that both
the platform accepts AND the visual editor renders (a draft can save fine yet
show a blank gray canvas if these are violated).

Reference implementation: `compose_comms.py` (`build_body`).

> **Adding a recipe?** These rules are the constraints; `RECIPE_BUILDING.md` is
> the step-by-step process (and a reusable prompt) for building one.

## The canvas is a mirror of the graph

Every journey is stored twice and both must agree (`activities[]` runtime +
`rawJourneyData` editor mirror). The canvas (`rawJourneyData.elements`) is:

- **Node element** — `id == activityId`; `type` ∈ {`source`, `action`, `exit`};
  `data` carries `ports` + `events` (+ schema fields, see rule 3).
- **Edge element** — `type: "default"`; `source`/`target` = the two activityIds;
  `sourceHandle = "<EventName>-<sourceActivityId>"`,
  `targetHandle = "input-<targetActivityId>"`; `data.eventName/eventType/activityName`.
  Keep `eventDisplayName` and `payloadKeys` — the renderer expects them.
- **Ports** on a node: outputs are `"<EventName>-<activityId>"`, the input is
  `"input-<activityId>"`. Because ids are embedded in port/handle strings,
  regenerating an activityId by **global string-replace** keeps ports, handles
  and edges in sync automatically.

## The rules (each one cost us a blank-canvas round)

1. **Every node needs BOTH `position` AND `positionAbsolute`** as `{x, y}`.
   A missing/`null` `positionAbsolute` throws `Cannot read properties of
   undefined (reading 'x')` in the editor's layout `forEach` → blank canvas.
   The synthesized terminal is the easy one to forget.

2. **Do not mix node schemas.** Two exist in captured journeys:
   - modern: `data` has `nodeType`, `order`, `type`, `boundaryDefinition`
   - old:    `data` has `activityType`, `activityDisplayName`, `withoutSourceHandle`
   Both render on their own; a journey with some nodes of each does not, and
   half-normalizing makes it worse. **Source every node of a recipe from ONE
   journey that renders**, and reproduce its shapes verbatim. Don't invent
   fields.

3. **De-nest lifted nodes.** When you pull a node that lived inside a
   boundary/parallel container (e.g. gow_comms' `notification_center`), strip
   `parentNode` and `extent` or the editor tries to read the missing parent's
   position.

4. **Linear-journey scaffolding:** `pathesConfiguration: {}`,
   `boundaryConfiguration: {}`, `exitCriteriaSettings: null`. (Splits/parallels
   populate these — not covered here.)

5. **Give it a start trigger:** set `isImmediatelyAfterPublish: true` (or a
   real `startAt`) in BOTH the top-level body and `rawJourneyData.infoValues`,
   or the editor warns "no start". Comms journeys are otherwise `isUnlimited:
   true` with no dates.

6. **Ids** — regenerate every `activityId`/`id` UUID consistently (global
   string-replace so embedded port/handle/edge refs move together). Strip
   lineage (`duplicatedFromId`/`Version`), blank `campaignConnectorConditions.
   campaignId`, strip `promotionDisplayId`. KEEP external refs (`contentId`,
   `frontId`, `CSE-*` email ids, NC `templates`).

7. **Wire only what you mean.** Set `nextActivityId` on the primary completion
   event of each node → the next node; leave secondary/failure events'
   `nextActivityId` null (the editor shows them as unconnected drop-ports, which
   is valid for a draft).

## Verify on disk BEFORE posting

`compose_comms.py::verify` checks, and any composer should:
- every `nextActivityId` resolves to an existing activity,
- every non-terminal activity has a canvas node,
- every `activitiesConfiguration` key maps to an activity,
- every edge's `source`/`target` is a real node,
- a terminal (`end_of_journey`) exists,
- every node has `position` + `positionAbsolute` with `x`/`y`.

The remaining unknown is only ever discovered from a HAR of the created draft —
open it, export HAR, diff the stored node/edge shapes against a journey that
renders. That workflow found rules 1–3 above.

## Knobs (values you change per campaign)

`extract_knobs.py` → `library/knobs.json`: per activity, the tunable leaf paths
(dotted, relative to the activity object) with example value + type, plus the
`external_refs` to KEEP and the `source_template` each path came from.

- Feed a path to `compose.py`'s `apply_values` via `values["set"][activityName]
  [dotted.path] = value` — see the deposit example in the test loop.
- **Knob paths are per-reference-journey.** The same activity can be shaped
  differently in different journeys (e.g. freebet is `properties.freeBetMaxAmount
  .CLP` in colocolo but `properties.freeBetAmount.CLP` in two_hours). Extract
  knobs from — or validate them against — the SAME reference a recipe uses.
- `apply_values` logs `MISS` for a path that doesn't exist and moves on; it
  never crashes the build. Check the log before trusting an override landed.
- CLP amounts are minor units (×100): `10000` = $100.
