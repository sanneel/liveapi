Colo Colo templates
===================

Colo Colo is configured as "the same journey as UDCH, one visual asset
differs". It does NOT need its own captured templates: it inherits the files
in templates/udch/ automatically.

To set the one differing image:
  Edit TEAMS["colocolo"].asset_overrides in journey-cloner/create_journeys.py
  and map the UDCH asset URL to the Colo Colo one, e.g.

      asset_overrides={
          UDCH_CATFISH_BANNER: "https://static.contentin.cloud/<colocolo>.png",
      }

Until an override is set, Colo Colo drafts render with the UDCH asset; every
other variable (club name, promocode, dates, 2H->FollowUp connector) is already
swapped correctly.

To instead use a fully separate Colo Colo design for a draft type, drop a
captured file here (followup.json / bfr.json / two_hours.json / aft.json) via
the admin Journey Cloner page with the club set to Colo Colo. A file present
here takes precedence over the inherited UDCH one.
