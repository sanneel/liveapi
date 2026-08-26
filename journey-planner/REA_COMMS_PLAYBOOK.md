# CRM COMMUNICATIONS PLAYBOOK

House rules for COMMUNICATION journeys (the MODE 5 comms chains: NC feed, popup,
SMS, email, push). Source: CRM Communications "Newcomer Onboarding Guide" v1.0,
August 2026. These are the conventions a human builder is held to, so a plan that
ignores them is wrong even when it composes cleanly.

Scope note: this governs the COMMS flow — the messaging journey — not the backend
promo mechanic (the bonus/freespin/wheel journey). A campaign usually has both,
and they are separate journeys (see SEPARATE FLOWS below).

## BRANDS

| Code | Brand | Also known as |
| --- | --- | --- |
| JBCL | JugaBet Chile | the reference brand — most complete toolset |
| JBCOM | JugaBet .com | |
| FZ | Fortunazo | ex FT, ex PMCL — a brief saying "PMCL" means Fortunazo |

The build PROCESS is identical across brands. What changes per brand: email
template id, on-site template ids, short-link domain, sending domain. Never
carry one brand's ids into another brand's journey.

## JOURNEY NAMING — the standard format

    BRAND | VERTICAL | Campaign description | DD.MM | Type

* BRAND — `JBCL` · `JBCOM` · `FZ`
* VERTICAL — `SP` (sport) · `CS` (casino) · `CS&SP` (both)
* Campaign — short, specific enough that someone who did not build it can tell
  which promo it is
* Date — `DD.MM` for one-offs, a month code (`AUG`) for recurring
* Type — `Comms` marks the COMMUNICATION flow, distinguishing it from the
  backend promo mechanic journey

Separator is a pipe with a space either side. Examples:

    JBCL | SP | Libertadores bet&get 10% | 18.08 | Comms
    JBCL | CS&SP | Libertadores bet&get 10% | 18.08 | Comms
    JBCL | SP | Monday Scratch Card E-Sport Follow Up AUG

Name every comms journey this way, including the `name` field of a MODE 5 chain
spec. Everyone finds journeys by scanning the list, so the name is the interface.

## CHANNELS AND THEIR NON-NEGOTIABLES

| Channel | Purpose | Non-negotiable |
| --- | --- | --- |
| Email | main promotional / lifecycle channel | built in Content Studio first, then loaded into the journey |
| SMS | high-reach, time-sensitive | must fit 1 SMS; no special characters; no emojis |
| Web push | browser alerts | standard journey block |
| Native push | Android app users only | app-audience filter; "open the app", not deep URLs |
| NC feed | sidebar notification centre | ALWAYS set a revoke timeline |
| Popup | on-site interruptive | ALWAYS set an expiry; links start from the slash |

WhatsApp is NOT integrated — a brief asking for WhatsApp is ⛔ UNCAPTURED.

Emojis: allowed in every channel EXCEPT SMS.

## SMS RULES (these control cost, not just style)

1. Open with the brand name and a separator — `Jugabet | `. Numbers are
   randomised, so without it the message reads as spam.
2. Must preview as 1 SMS with 0 overage.
3. Strip every special Spanish character — `ñ ¿ ¡ í á é ó ú` and accents — to
   plain ASCII. One special character can count as ~10 and silently double or
   triple the bill. Write "manana" not "mañana", "Ganaste" not "¡Ganaste!".
4. No emojis.
5. An English variant is not required — the same Spanish text in both fields is
   acceptable.
6. The link goes LAST, at the end of the message text.
7. Use the brand-domain merge tag, not a typed URL, with the slug pasted
   directly against it and NO space between. Delete the hardcoded URL.
8. Set the brand-domain field to Required, so the SMS will not fire if the site
   is broken.
9. Tick auto-login when the link points at the main site.

## SHORT-LINK TRACKING DOMAINS (SMS)

Wrong domain = message delivers but Tableau reports nothing. Always the
`https://` variant.

| Brand | Short URL domain |
| --- | --- |
| JBCL | https://juga.cl |
| JBCOM | https://jug.bet |
| FZ | https://frtnz.cl |

## LINK FORMATS BY CHANNEL

| Where | Format | Example |
| --- | --- | --- |
| Popup, NC feed | relative path from the slash | `/promo/promotion/` |
| SMS, email | brand domain variable + slug | `https://{{BrandDomain}}/promo/promotion/` |

Smartico links have TWO types and using the wrong one breaks the destination:

| Comms type | Link form |
| --- | --- |
| INTERNAL — NC feed, popup (arrives inside our site) | `https://{{BrandDomain}}/#smartico_dl=dp:gf_missions&id=25028` |
| EXTERNAL — SMS, email (arrives from outside) | `https://{{BrandDomain}}/#_smartico_dp=dp:gf_matchx&id=6920` |

Type 1 (`smartico_dl`) works only on-site. Type 2 (`_smartico_dp`) is for
anything arriving from outside. Never mix them.

## ON-SITE: NC FEED

* Channel Notification · Type "Information (deprecated)" · Category All. The
  deprecation label is misleading — it is the correct selection.
* Use the brand's customisable template id (see TEMPLATE IDS). Never a random one.
* CTA text exactly as the content creator supplied it.
* Revoke timeline is MANDATORY (e.g. 4 days) or expired promos sit in the sidebar.
* Do NOT target players inactive 60+ days.

## ON-SITE: POPUP

* Channel Pop-up · Type "Catfish (deprecated)" — again, the correct selection
  despite the label.
* Copy is 1–3 short lines.
* Background asset goes to the Media Library first, then insert the link.
* Expiry is MANDATORY, a couple of days. Without it a player returning after a
  week is hit with ~15 stacked popups. This is the single most common newcomer
  mistake and it is player-visible.

## NATIVE (APP) PUSH

* Audience filter, including the OR: `channel = NATIVE_ANDROID_IOLITE OR
  is_app_player = True`.
* Navigation: "open the app". Deep URLs are unreliable.
* Set a push lifetime / hard expiry for time-sensitive promos (a match kickoff)
  so stale alerts clear.

## EMAIL

* Duplicate the master template; never edit the master. Rename the copy with the
  brand prefix (`JBCL_`, `JBCOM_`, `VIP_`).
* Copy goes in the HTML window, not the visual window. `<br>` for spacing,
  `<b>…</b>` for headers.
* Replace the header image link AND both destination URLs (image + CTA).
* Do not touch the footer "block" references.
* Send From set explicitly to the brand name.
* Keep "check if email is verified" ticked — unverified sends bounce and incur
  delivery-attempt fees.

## JOURNEY STRUCTURE

### The wait rule (hard platform constraint)
An engagement split CANNOT sit directly after a message block. A Wait Time block
must come immediately after the communication item to unlock the split. There is
no single standard buffer:
* 15–30 min for a quick on-site follow-up
* up to an hour when waiting on SMS click behaviour
* a fixed calendar date for multi-day promos

After the wait, split on behaviour (delivered / clicked). Route clickers OUT of
the journey; send the unengaged path to a backup channel. Rename the true/false
paths so the journey can be audited. This is what stops the same promo being
pushed across every channel and blowing the monthly budget.

### Decision splits
Split by historical activity BEFORE sending. Example: on a 50,000-player blast,
look back 30 days — email only to players who opened at least one email in the
window, and pivot the rest to SMS.

### Delays
`Wait 1 Day` to space multi-day promos. Absolute time rules to pin an action to
a timestamp — e.g. hold until exactly 2 hours before kickoff.

### Exit criteria
When the flow is tethered to a boundary event (Bet & Get, deposit match),
configure Check Exit Criteria on the wait-state node. A player who completes the
deposit target at step 2 must stop receiving the remaining reminders.

### Separate flows vs boundary events
* SEPARATE FLOW — comms run independently of the backend mechanic. A cashback
  engine pays out Tuesday; the marketing comms flow runs Monday, not wired into
  the calculation.
* BOUNDARY EVENT — messaging that must fire in parallel with a transaction or
  activity, e.g. an on-site message at the moment a free spin is credited. For
  multi-step campaigns, put a distinct boundary alert alongside each step.

## CHANNEL SEQUENCING

| Journey type | Sequence |
| --- | --- |
| Sports one-time | SMS first |
| Tournament CS | Email → if not opened → SMS → NC feed |
| Tournament Mixed | SMS → NC feed → if not opened → Popup |

## TEMPLATE IDS

A snapshot — the CRM team channel is the source of truth. NEVER invent a
template id. If the brief does not give you one and the channel needs one, ask
with ❓ and leave the node out.

### Email (Content Studio, `template` on an email node)

| Brand / vertical | Template ID | Name |
| --- | --- | --- |
| Fortunazo | CSE-0-9033 | FZCL CS – Template |
| Fortunazo | CSE-0-9088 | FZCL SP – Template |
| JBCL Sport | CSE-0-10690 | Football |
| JBCL Sport | CSE-0-10709 | Tennis |
| JBCL Sport | CSE-0-10710 | Basketball |
| JBCL Sport | CSE-0-10483 | Odds + Image |
| JBCL Sport | CSE-0-10502 | Newsletter |
| JBCL Sport | CSE-0-10428 | Odds |
| JBCL Sport | CSE-0-10437 | Odds + CTA |
| JBCL Sport | CSE-0-5170 | JBCL SP – Template Sep 2025 |
| JBCL Casino | CSE-0-5168 | JBCL CS – Template Sep 2025 |
| JBCL Casino | CSE-0-6316 | JBCL CS – Template New 2025 |
| JBCL Casino | CSE-0-5425 | JBCL CS – GOW Template |
| JBCOM | CSE-0-12658 | JBCOM Casino simple |
| JBCOM | CSE-0-12650 | JBCOM Nice Template |
| JBCOM | CSE-0-12636 | JBCOM GOW |
| JBCOM | CSE-0-12635 | SP Template |

### On-site

| Brand | NC feed (Notification) | Popup (Catfish) |
| --- | --- | --- |
| JBCL | 1935 | 20678 |
| FZ (ex FT / PMCL) | 16001 | 15999 |
| JBCOM | 24714 | 24715 |

## INPUT SOURCE

* DWH segment — the default for the vast majority of comms.
* CSV upload — only when precise filtering is needed (specific bonus targeting)
  or an exact predetermined player list must be reached.

## WHAT TESTING HAS SHOWN

| Element | Verdict |
| --- | --- |
| ALL CAPS subject lines | perform BETTER — recommend them |
| Timers in emails | perform BETTER — recommend them |
| Firstname in SMS | no measurable difference |
| GIF buttons in emails | no measurable difference |

## ASK, DO NOT INVENT

Flag with ❓ and leave the node out rather than guessing:
* email template id (CSE-0-…)
* NC / popup template id
* artwork URL (NC icon, popup background, push image)
* the destination slug
* Smartico `dp:` name and `id`

## GOTCHAS

* Draft-journey email tests render differently from live — the real test is from
  the PUBLISHED journey.
* Deep links in native push are unreliable — default to "open the app".
* "Catfish (deprecated)" and "Information (deprecated)" ARE the correct
  selections; the label lies.
* A missing popup expiry is the most common newcomer mistake.
* The wrong short-link domain kills reporting silently — delivery succeeds,
  Tableau shows nothing.
