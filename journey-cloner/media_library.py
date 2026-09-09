"""Media-library constants, shared by everything that uploads artwork.

These lived in comms_campaign.py, which meant nc_discount_campaign.py,
sport_comms_campaign.py and journey_composer.py each imported an 882-line
campaign generator to read one folder id. That is the whole coupling between
them, so it belongs here instead.

Captured from the backoffice's own photo picker — see
REA_BACKOFFICE_AND_JOURNEYS.md for how.
"""
from __future__ import annotations

# The media-library folder the backoffice's own photo picker uploads into.
DEFAULT_FOLDER_ID = "c5c7c614-5169-4346-b90b-8225836a1c63"
# The public site domain SMS links resolve to (the {{BrandDomain}} dwh variable
# in the SMS template, flattened where SMS text is static).
DEFAULT_PUBLIC_DOMAIN = "win.jugabet.cl"
